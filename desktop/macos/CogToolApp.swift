import SwiftUI
import AppKit
import UniformTypeIdentifiers
import Darwin

private let accent = Color(red: 0.13, green: 0.43, blue: 0.48)

private struct ModelTask: Identifiable {
    let id: String
    let name: String
    let stepCount: Int
}

private struct ModelSummary {
    let url: URL
    let id: String
    let name: String
    let engine: String
    let tasks: [ModelTask]
    let frameCount: Int
    let scope: String?
    let policy: String?

    init(url: URL, data: [String: Any]) throws {
        guard let id = data["id"] as? String, let name = data["name"] as? String,
              let engine = data["engine"] as? String,
              let rows = data["tasks"] as? [[String: Any]] else {
            throw EngineFailure.message("The project information is incomplete. Check the project file.")
        }
        self.url = url
        self.id = id
        self.name = name
        self.engine = engine
        self.tasks = rows.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            return ModelTask(id: id, name: item["name"] as? String ?? id,
                             stepCount: item["step_count"] as? Int ?? 0)
        }
        self.frameCount = data["frame_count"] as? Int ?? 0
        self.scope = data["scope"] as? String
        self.policy = data["run_policy"] as? String
        guard !self.tasks.isEmpty else { throw EngineFailure.message("This project has no runnable tasks.") }
    }

    var engineTitle: String {
        switch engine {
        case "klm_baseline": return "KLM serial baseline"
        case "cogtool_motor_subset_experimental": return "Motor subset · Experimental"
        case "cogtool_control_prefix_experimental": return "Control subset · Experimental"
        default: return engine
        }
    }
}

private struct ResultStep: Identifiable {
    let id: Int
    let operation: String
    let target: String
    let duration: String
    let note: String

    static let names = ["point": "Point", "click": "Click", "right_click": "Right-click", "key": "Keystroke",
                        "home": "Home", "think": "Think", "look_at": "Look at", "wait": "Wait", "transition": "Transition"]
}

private struct Prediction {
    let data: [String: Any]
    let output: URL
    let steps: [ResultStep]
    let raw: String
    let status: String
    let predictedTime: Double?
    let runtime: Double?

    init(data: [String: Any], output: URL) throws {
        self.data = data
        self.output = output
        let identity = data["distribution_identity"] as? [String: Any] ?? [:]
        self.predictedTime = (data["predicted_time_s"] as? NSNumber)?.doubleValue
        self.runtime = (data["program_runtime_s"] as? NSNumber)?.doubleValue
        self.status = data["completion_status"] as? String ?? identity["execution_status"] as? String
            ?? (self.predictedTime == nil ? "partial" : "complete")
        let events = data["events"] as? [[String: Any]] ?? []
        let isSerial = (data["engine"] as? [String: Any])?["name"] as? String == "klm_baseline"
        self.steps = (data["steps"] as? [[String: Any]] ?? []).enumerated().map { offset, row in
            let index = row["index"] as? Int ?? offset
            let op = row["op"] as? String ?? "—"
            let matching = events.filter { ($0["step_index"] as? Int) == index }
            let explicit = (row["duration_s"] as? NSNumber)?.doubleValue
            let recorded = isSerial && matching.count == 1 ? (matching[0]["duration_s"] as? NSNumber)?.doubleValue : nil
            let seconds = recorded ?? explicit
            let duration = seconds.map { String(format: "%.3f s", $0) } ?? "—"
            let target = row["target"] as? String ?? row["key"] as? String ?? "—"
            let note = row["note"] as? String ?? row["origin"] as? String ?? ""
            return ResultStep(id: offset, operation: ResultStep.names[op] ?? op,
                              target: target, duration: duration, note: note)
        }
        self.raw = String(data: try JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]), encoding: .utf8) ?? ""
    }

    var isComplete: Bool { status == "complete" }
    var statusTitle: String { isComplete ? "Complete" : "Incomplete · Results saved" }
    var reason: String? { data["termination_reason"] as? String }
}

private enum EngineFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

/// Reads the two pipes concurrently so a verbose engine cannot block its parent.
private final class EngineProcess: @unchecked Sendable {
    static let shared = EngineProcess()
    private let lock = NSLock()
    private var active: Process?
    private var quitting = false

    func request(_ arguments: [String]) async throws -> [String: Any] {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    guard let executable = Bundle.main.resourceURL?.appendingPathComponent("engine/cogtool-engine"),
                          FileManager.default.isExecutableFile(atPath: executable.path) else {
                        throw EngineFailure.message("The bundled prediction engine is missing or cannot run. Reinstall the complete CogTool.app.")
                    }
                    let process = Process()
                    let stdout = Pipe(), stderr = Pipe()
                    process.executableURL = executable
                    process.arguments = arguments
                    process.standardOutput = stdout
                    process.standardError = stderr
                    process.standardInput = FileHandle.nullDevice
                    self.lock.lock()
                    if self.quitting || self.active != nil {
                        self.lock.unlock()
                        throw EngineFailure.message("The prediction engine is busy or shutting down. Try again shortly.")
                    }
                    self.active = process
                    do { try process.run() } catch {
                        self.active = nil
                        self.lock.unlock()
                        throw error
                    }
                    self.lock.unlock()
                    let errorBox = DataBox()
                    let drain = DispatchGroup()
                    drain.enter()
                    DispatchQueue.global(qos: .userInitiated).async {
                        errorBox.data = stderr.fileHandleForReading.readDataToEndOfFile()
                        drain.leave()
                    }
                    let response = stdout.fileHandleForReading.readDataToEndOfFile()
                    drain.wait()
                    process.waitUntilExit()
                    self.lock.lock()
                    self.active = nil
                    self.lock.unlock()
                    let parsed = (try? JSONSerialization.jsonObject(with: response)) as? [String: Any]
                    if let parsed, parsed["ok"] as? Bool == true,
                       process.terminationReason == .exit, [Int32(0), Int32(3)].contains(process.terminationStatus) {
                        continuation.resume(returning: parsed)
                    } else {
                        let detail = parsed?["error"] as? String
                            ?? String(data: errorBox.data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
                        let fallback = "The prediction engine stopped unexpectedly (code \(process.terminationStatus))."
                        throw EngineFailure.message(detail?.isEmpty == false ? String(detail!.prefix(5000)) : fallback)
                    }
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    func shutdown() {
        lock.lock()
        quitting = true
        let process = active
        lock.unlock()
        guard let process, process.isRunning else { return }
        process.terminate()
        // The engine belongs to this app. Do not leave it running after Quit.
        let deadline = Date().addingTimeInterval(0.4)
        while process.isRunning && Date() < deadline { usleep(10_000) }
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
    }

    private final class DataBox { var data = Data() }
}

private final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { EngineProcess.shared.shutdown() }
}

@MainActor
private final class Workspace: ObservableObject {
    @Published var model: ModelSummary?
    @Published var taskID = "" {
        didSet { if taskID != oldValue { prediction = nil } }
    }
    @Published var prediction: Prediction?
    @Published var busy = false
    @Published var activity = ""
    @Published var error: String?
    @Published var showingRaw = false
    @Published var imported: [URL] = []
    @Published var outputParent: URL
    private var started = false
    private var pendingOpenURLs: [URL] = []

    let examples: [(file: String, title: String, subtitle: String, icon: String)] = [
        ("single_click", "Point and click", "A single-button interaction", "cursorarrow.click"),
        ("text_entry", "Text entry", "Click, home and type", "text.cursor"),
        ("two_page_wait", "Page transition", "Navigation and system wait", "rectangle.on.rectangle"),
        ("explicit_operators", "Explicit operators", "Explore individual steps", "list.number")
    ]

    init() {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents")
        outputParent = documents.appendingPathComponent("CogTool Results", isDirectory: true)
    }

    func exampleURL(_ name: String) -> URL? {
        Bundle.main.resourceURL?.appendingPathComponent("Examples/\(name).json")
    }

    func start() async {
        guard !started else { return }
        started = true
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "--ui-smoke-test"), args.count > index + 1 {
            let report = URL(fileURLWithPath: args[index + 1])
            outputParent = report.deletingLastPathComponent().appendingPathComponent("ui-smoke-results", isDirectory: true)
            if let url = exampleURL("single_click") { await load(url) }
            if model != nil { await runPrediction() }
            var evidence: [String: Any] = ["ok": prediction?.isComplete == true, "window_count": NSApp.windows.count,
                                           "project_name": model?.name ?? "", "task_id": taskID,
                                           "engine": model?.engine ?? "", "error": error ?? ""]
            if let prediction {
                evidence["predicted_time_s"] = prediction.predictedTime
                evidence["completion_status"] = prediction.status
                evidence["step_count"] = prediction.steps.count
                evidence["output_dir"] = prediction.output.path
                evidence["raw_result_length"] = prediction.raw.count
            }
            do {
                try FileManager.default.createDirectory(at: report.deletingLastPathComponent(), withIntermediateDirectories: true)
                try JSONSerialization.data(withJSONObject: evidence, options: [.prettyPrinted, .sortedKeys]).write(to: report, options: .atomic)
            } catch { fputs("UI smoke report: \(error.localizedDescription)\n", stderr) }
            NSApplication.shared.terminate(nil)
        } else if !pendingOpenURLs.isEmpty {
            await openNextPendingProject()
        } else if let url = exampleURL("single_click") { await load(url) }
    }

    func receiveOpenURL(_ url: URL) async {
        pendingOpenURLs.append(url)
        if started { await openNextPendingProject() }
    }

    private func openNextPendingProject() async {
        guard !busy, !pendingOpenURLs.isEmpty else { return }
        await load(pendingOpenURLs.removeFirst())
    }

    private func finishActivity() {
        busy = false
        activity = ""
        if !pendingOpenURLs.isEmpty {
            Task { await openNextPendingProject() }
        }
    }

    func openProject() {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.title = "Open a CogTool Project"
        panel.message = "Choose a CogTool-Py JSON project file."
        panel.allowedContentTypes = [.json]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await load(url) }
    }

    func load(_ url: URL) async {
        guard !busy else { return }
        busy = true
        activity = "Loading project…"
        error = nil
        model = nil
        taskID = ""
        prediction = nil
        defer { finishActivity() }
        do {
            let response = try await EngineProcess.shared.request(["inspect", url.path])
            guard let data = response["project"] as? [String: Any] else {
                throw EngineFailure.message("The prediction engine did not return any project information.")
            }
            let summary = try ModelSummary(url: url, data: data)
            model = summary
            taskID = summary.tasks.first?.id ?? ""
            prediction = nil
            if !url.path.contains("/Contents/Resources/Examples/") && !imported.contains(url) {
                imported.insert(url, at: 0)
            }
        } catch { self.error = error.localizedDescription }
    }

    func chooseOutput() {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose Output Folder"
        panel.message = "Each prediction creates a new results folder here."
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        if FileManager.default.fileExists(atPath: outputParent.path) { panel.directoryURL = outputParent }
        if panel.runModal() == .OK, let url = panel.url { outputParent = url }
    }

    func runPrediction() async {
        guard !busy, let model, !taskID.isEmpty else { return }
        busy = true
        activity = "Running prediction…"
        error = nil
        prediction = nil
        defer { finishActivity() }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        let safeName = String(model.id.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "_" }.prefix(48))
        let folder = "\(formatter.string(from: Date()))_\(safeName)_\(UUID().uuidString.prefix(8))"
        let output = outputParent.appendingPathComponent(folder, isDirectory: true)
        do {
            let response = try await EngineProcess.shared.request(["predict", model.url.path, "--task", taskID, "--out", output.path])
            guard let result = response["result"] as? [String: Any], let path = response["output_dir"] as? String else {
                throw EngineFailure.message("The engine returned a response, but the result or its saved location is missing.")
            }
            prediction = try Prediction(data: result, output: URL(fileURLWithPath: path))
        } catch { self.error = error.localizedDescription }
    }

    func showOutput() {
        guard let prediction else { return }
        NSWorkspace.shared.open(prediction.output)
    }
}

private struct WorkspaceView: View {
    @EnvironmentObject private var workspace: Workspace

    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 10) {
                    Image(systemName: "cursorarrow.motionlines").font(.system(size: 26, weight: .medium)).foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("CogTool").font(.system(size: 22, weight: .semibold, design: .rounded))
                        Text("Interaction time prediction").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.top, 12)
                Button(action: workspace.openProject) { Label("Open Project…", systemImage: "folder")
                    .frame(maxWidth: .infinity, alignment: .leading) }
                    .controlSize(.large).disabled(workspace.busy)
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("EXAMPLES").font(.caption.weight(.semibold)).foregroundStyle(.secondary).padding(.leading, 9)
                        ForEach(workspace.examples, id: \.file) { example in
                            Button {
                                if let url = workspace.exampleURL(example.file) { Task { await workspace.load(url) } }
                            } label: {
                                HStack(spacing: 11) {
                                    Image(systemName: example.icon).font(.system(size: 17)).frame(width: 23)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(example.title).font(.system(size: 13, weight: .medium))
                                        Text(example.subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
                                    }
                                    Spacer(minLength: 0)
                                }.padding(11).contentShape(Rectangle())
                                    .background(workspace.model?.url == workspace.exampleURL(example.file) ? accent.opacity(0.12) : .clear,
                                                in: RoundedRectangle(cornerRadius: 9))
                            }.buttonStyle(.plain).disabled(workspace.busy)
                        }
                        if !workspace.imported.isEmpty {
                            Text("OPENED PROJECTS").font(.caption.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 15).padding(.leading, 9)
                            ForEach(workspace.imported, id: \.path) { url in
                                Button { Task { await workspace.load(url) } } label: {
                                    Label(url.deletingPathExtension().lastPathComponent, systemImage: "doc.text")
                                        .lineLimit(2).frame(maxWidth: .infinity, alignment: .leading).padding(10)
                                        .background(workspace.model?.url == url ? accent.opacity(0.12) : .clear,
                                                    in: RoundedRectangle(cornerRadius: 9))
                                }.buttonStyle(.plain).disabled(workspace.busy)
                            }
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 5) {
                    Label("Runs on your Mac", systemImage: "desktopcomputer").font(.caption.weight(.medium))
                    Text("Projects and prediction results stay on this Mac.")
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }.padding(.bottom, 12)
            }.padding(.horizontal, 15)
                .navigationSplitViewColumnWidth(min: 220, ideal: 245, max: 295)
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if let model = workspace.model {
                        header(model)
                        configuration(model)
                        if let error = workspace.error { errorBanner(error) }
                        resultSection
                        outputSection
                    } else {
                        if let error = workspace.error { errorBanner(error) }
                        ContentUnavailableView("Open a CogTool Project", systemImage: "doc.badge.plus",
                                               description: Text("Choose an example in the sidebar or open your own JSON project."))
                            .frame(minHeight: 420)
                    }
                }.padding(28).frame(maxWidth: 1200, alignment: .leading).frame(maxWidth: .infinity)
            }.background(Color(nsColor: .windowBackgroundColor))
        }
        .tint(accent)
        .frame(minWidth: 1000, minHeight: 700)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await workspace.runPrediction() } } label: { Label("Run Prediction", systemImage: "play.fill") }
                    .disabled(workspace.busy || workspace.model == nil).keyboardShortcut("r", modifiers: .command)
            }
        }
        .sheet(isPresented: $workspace.showingRaw) { rawSheet }
        .task { await workspace.start() }
        .onOpenURL { url in Task { await workspace.receiveOpenURL(url) } }
    }

    private func header(_ model: ModelSummary) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("MODEL WORKSPACE").font(.system(size: 11, weight: .semibold)).tracking(1.5).foregroundStyle(accent)
            Text(model.name).font(.system(size: 29, weight: .semibold)).textSelection(.enabled)
            HStack(spacing: 16) {
                Label("\(model.frameCount) \(model.frameCount == 1 ? "frame" : "frames")", systemImage: "rectangle")
                Label("\(model.tasks.count) \(model.tasks.count == 1 ? "task" : "tasks")", systemImage: "list.bullet.rectangle")
                Text(model.url.lastPathComponent).lineLimit(1).help(model.url.path)
            }.font(.system(size: 12)).foregroundStyle(.secondary)
        }
    }

    private func configuration(_ model: ModelSummary) -> some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Prediction engine").font(.caption).foregroundStyle(.secondary)
                    Text(model.engineTitle).font(.system(size: 14, weight: .semibold))
                    Text(model.engine).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary).textSelection(.enabled)
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Selected task").font(.caption).foregroundStyle(.secondary)
                    Picker("Selected task", selection: $workspace.taskID) {
                        ForEach(model.tasks) { task in Text("\(task.name) · \(task.stepCount) \(task.stepCount == 1 ? "step" : "steps")").tag(task.id) }
                    }.labelsHidden().disabled(workspace.busy).frame(minWidth: 200)
                }.frame(maxWidth: .infinity, alignment: .leading)
                Button { Task { await workspace.runPrediction() } } label: {
                    HStack(spacing: 8) {
                        if workspace.busy { ProgressView().controlSize(.small) }
                        else { Image(systemName: "play.fill") }
                        Text(workspace.busy ? "Working…" : "Run Prediction")
                    }.frame(minWidth: 100)
                }.buttonStyle(.borderedProminent).controlSize(.large).disabled(workspace.busy)
                    .padding(.top, 14)
            }
            if model.scope != nil || model.policy != nil {
                HStack(spacing: 18) {
                    if let scope = model.scope { Text("Scope: \(scope)") }
                    if let policy = model.policy { Text("Run policy: \(policy)") }
                }.font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            }
            Text("Uses the engine and parameters saved in the project. Predictions apply within the model’s declared scope.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 14))
    }

    @ViewBuilder private var resultSection: some View {
        if let prediction = workspace.prediction {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 15) {
                    metric("Predicted task time", value: prediction.predictedTime.map { String(format: "%.3f", $0) } ?? "—", unit: "s", icon: "stopwatch")
                    metric("Computation time", value: prediction.runtime.map { String(format: "%.4f", $0) } ?? "—", unit: "s", icon: "cpu")
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Run status").font(.caption).foregroundStyle(.secondary)
                        Label(prediction.statusTitle, systemImage: prediction.isComplete ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                            .font(.system(size: 15, weight: .semibold)).foregroundStyle(prediction.isComplete ? accent : .orange)
                        Text("\(prediction.steps.count) generated \(prediction.steps.count == 1 ? "step" : "steps")").font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(18)
                        .frame(minHeight: 116).background(.background, in: RoundedRectangle(cornerRadius: 12))
                }
                if !prediction.isComplete {
                    Text("The task did not finish, so no complete task-time prediction is shown. Available results have been saved.\(prediction.reason.map { " Termination reason: \($0)" } ?? "")")
                        .font(.caption).foregroundStyle(.orange).textSelection(.enabled)
                }
                HStack {
                    Text("Prediction steps").font(.system(size: 17, weight: .semibold))
                    Spacer()
                    Button("View Raw Results") { workspace.showingRaw = true }
                }
                Table(prediction.steps) {
                    TableColumn("Step") { step in Text("\(step.id + 1)").foregroundStyle(.secondary) }.width(40)
                    TableColumn("Operation", value: \.operation).width(min: 70, ideal: 95)
                    TableColumn("Target / key", value: \.target).width(min: 100, ideal: 150)
                    TableColumn("Duration", value: \.duration).width(90)
                    TableColumn("Note", value: \.note)
                }.frame(height: min(330, max(145, CGFloat(prediction.steps.count * 29 + 32))))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                Text("The serial baseline shows event durations. Other engines show only explicit step durations. See raw results for full event timing.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        } else {
            VStack(spacing: 12) {
                Image(systemName: workspace.busy ? "hourglass" : "chart.bar.xaxis")
                    .font(.system(size: 30, weight: .light)).foregroundStyle(accent)
                Text(workspace.busy ? workspace.activity : "Ready to run a prediction").font(.system(size: 17, weight: .medium))
                Text("Run the model to see task time, generated steps and full results.")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity).frame(height: 250)
                .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 14))
        }
    }

    private func metric(_ label: String, value: String, unit: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(label, systemImage: icon).font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(value).font(.system(size: 29, weight: .semibold, design: .rounded)).monospacedDigit()
                Text(unit).font(.caption).foregroundStyle(.secondary)
            }
            Text(label == "Predicted task time" ? "Estimated interaction time" : "Time spent computing on this Mac")
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(18).frame(minHeight: 116)
            .background(.background, in: RoundedRectangle(cornerRadius: 12))
    }

    private var outputSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Results folder", systemImage: "folder").font(.system(size: 13, weight: .medium))
                Spacer()
                Button("Change Folder…", action: workspace.chooseOutput).disabled(workspace.busy)
                if workspace.prediction != nil { Button("Show in Finder", action: workspace.showOutput) }
            }
            Text(workspace.prediction?.output.path ?? workspace.outputParent.path)
                .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                .textSelection(.enabled).lineLimit(3)
            Text("Each run creates a new folder and keeps all previous results.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(18).background(.background, in: RoundedRectangle(cornerRadius: 12))
    }

    private func errorBanner(_ error: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 5) {
                Text("Could not complete the operation").font(.system(size: 13, weight: .semibold))
                Text(error).font(.system(size: 12)).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Button { workspace.error = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
        }.padding(15).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
    }

    private var rawSheet: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text("Raw Prediction Results").font(.title2.weight(.semibold))
                Spacer()
                Button("Copy JSON") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(workspace.prediction?.raw ?? "", forType: .string)
                }
                Button("Done") { workspace.showingRaw = false }.keyboardShortcut(.defaultAction)
            }
            ScrollView([.vertical, .horizontal]) {
                Text(workspace.prediction?.raw ?? "").font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(14)
            }.background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 9))
        }.padding(22).frame(width: 880, height: 620)
    }
}

@main
@MainActor
struct CogToolApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var workspace = Workspace()

    var body: some Scene {
        Window("CogTool", id: "main") {
            WorkspaceView().environmentObject(workspace)
        }
        .defaultSize(width: 1150, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Project…", action: workspace.openProject)
                    .keyboardShortcut("o", modifiers: .command).disabled(workspace.busy)
            }
            CommandMenu("Prediction") {
                Button("Run Prediction") { Task { await workspace.runPrediction() } }
                    .keyboardShortcut("r", modifiers: .command).disabled(workspace.busy || workspace.model == nil)
                Button("View Raw Results") { workspace.showingRaw = true }.disabled(workspace.prediction == nil)
                Divider()
                Button("Choose Output Folder…", action: workspace.chooseOutput).disabled(workspace.busy)
                Button("Show Results in Finder", action: workspace.showOutput).disabled(workspace.prediction == nil)
            }
        }
    }
}

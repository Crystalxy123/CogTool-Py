package org.cogtoolvalidation;

import edu.cmu.cs.hcii.cogtool.CogToolPref;
import edu.cmu.cs.hcii.cogtool.model.*;
import edu.cmu.cs.hcii.cogtool.util.*;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;

/** Observational harness; all reading, geometry, generation and Lisp are upstream. */
public final class JavaGenerationMain {
    static final String COMMIT = "a91d91e8dcf95d762b6e08020029a36ea079bbba";
    static final IdentityHashMap<Object, String> ids = new IdentityHashMap<Object, String>();
    static final List<Object> calls = new ArrayList<Object>();
    static Map<String,Object> map(Object... pairs) {
        Map<String,Object> m = new LinkedHashMap<String,Object>();
        for (int i=0;i<pairs.length;i+=2) m.put((String)pairs[i],pairs[i+1]);
        return m;
    }
    static String id(Object obj) {
        if (obj == null) return null;
        if (!ids.containsKey(obj)) ids.put(obj,"observed-"+(ids.size()+1));
        return ids.get(obj);
    }
    static Object field(Object obj, String name) throws Exception {
        for (Class<?> c=obj.getClass(); c!=null; c=c.getSuperclass()) {
            try { Field f=c.getDeclaredField(name); f.setAccessible(true); return f.get(obj); }
            catch (NoSuchFieldException e) { /* search the real superclass */ }
        }
        throw new NoSuchFieldException(name);
    }
    static String json(Object value) {
        if (value==null) return "null";
        if (value instanceof Boolean || value instanceof Number) return value.toString();
        if (value instanceof Map) {
            StringBuilder b=new StringBuilder("{"); boolean first=true;
            for (Object entryObj:((Map<?,?>)value).entrySet()) {
                Map.Entry<?,?> e=(Map.Entry<?,?>)entryObj;
                if (!first) b.append(","); first=false;
                b.append(json(e.getKey().toString())).append(":").append(json(e.getValue()));
            }
            return b.append("}").toString();
        }
        if (value instanceof Iterable) {
            StringBuilder b=new StringBuilder("["); boolean first=true;
            for (Object e:(Iterable<?>)value) { if (!first)b.append(",");first=false;b.append(json(e)); }
            return b.append("]").toString();
        }
        String s=value.toString(); StringBuilder b=new StringBuilder("\"");
        for (int i=0;i<s.length();i++) {
            char c=s.charAt(i);
            if(c=='\\'||c=='"') b.append('\\').append(c);
            else if(c<32) b.append(String.format("\\u%04x",(int)c));
            else b.append(c);
        }
        return b.append('"').toString();
    }
    static void write(Path out,String name,Object value) throws Exception {
        Files.write(out.resolve(name),(json(value)+"\n").getBytes(StandardCharsets.UTF_8));
    }
    static String digest(byte[] content) throws Exception {
        StringBuilder b=new StringBuilder();
        for(byte x:MessageDigest.getInstance("SHA-256").digest(content))b.append(String.format("%02x",x&255));
        return b.toString();
    }
    static String name(TransitionSource source) { return source==null?null:source.getName(); }
    static String frameName(Frame frame) {return frame==null?null:frame.getName();}
    static Object rect(DoubleRectangle b) {return b==null?null:map("x",b.x,"y",b.y,"width",b.width,"height",b.height);}
    static Object state(DefaultModelGeneratorState s) {
        return map("class",s.getClass().getName(),"mouse_hand",s.getMouseHand(),
                   "left_hand",String.valueOf(s.getHandLocation(false)),"right_hand",String.valueOf(s.getHandLocation(true)),
                   "last_clicked",name(s.getLastClickedWidget()),"last_moved",name(s.getLastMovedToWidget()),
                   "last_looked",name(s.getLastLookedAtWidget()),"keyboard_modifiers",s.getKeyboardModifiers(),
                   "last_step_is_mental",s.lastStepIsMental());
    }
    static Object action(AAction a) throws Exception {
        if(a==null)return null;
        Map<String,Object> m=map("class",a.getClass().getName(),"text",a.getLocalizedString());
        if(a instanceof ButtonAction) {
            ButtonAction b=(ButtonAction)a;
            m.put("button",String.valueOf(b.getButton()));m.put("press_type",String.valueOf(b.getPressType()));
            m.put("modifiers",b.getModifiers());
        }
        if(a instanceof KeyAction) {
            KeyAction k=(KeyAction)a;
            m.put("text",k.getText());m.put("is_command",k.isCommand());
            m.put("modifiers",k.getModifiers());m.put("press_type",String.valueOf(k.getPressType()));
        }
        if(a instanceof HomeAction) {
            HomeAction h=(HomeAction)a;
            m.put("hand",h.forWhichHand()?"right":"left");
            m.put("home_target",String.valueOf(h.getHomeTarget()));
        }
        return m;
    }
    static Map<String,Object> source(TransitionSource s) throws Exception {
        if(s==null)return null;
        return map("id",id(s),"class",s.getClass().getName(),"name",name(s),"frame",frameName(s.getFrame()),
                   "kind",s instanceof InputDevice?"input_device":s instanceof IWidget?"widget":"unknown",
                   "device_type",s instanceof InputDevice?String.valueOf(((InputDevice)s).getDeviceType()):null,
                   "widget_type",s instanceof IWidget?String.valueOf(((IWidget)s).getWidgetType()):null);
    }
    static Object transition(Transition t) throws Exception {
        return map("id",id(t),"source",name(t.getSource()),"destination",frameName(t.getDestination()),
                   "source_details",source(t.getSource()),
                   "action",action(t.getAction()),"delay_s",t.getDelayInSecs(),"delay_label",t.getDelayLabel());
    }
    static Object step(AScriptStep s, Demonstration demo) throws Exception {
        Map<String,Object> m=map("class",s.getClass().getName(),"id",id(s),"owner_id",id(s.getOwner()),
                                "owner_demonstration_index",demo.getSteps().indexOf(s.getOwner()),
                                "demonstrated",s.isDemonstrated(),"inserted_by_user",s.isInsertedByUser(),
                                "initially_generated",s.isInitiallyGenerated(),"invalid",s.isInvalid(),"obsolete",s.isObsolete(),
                                "frame",frameName(s.getCurrentFrame()),"destination",frameName(s.getDestinationFrame()),
                                "focus",name(s.getStepFocus()),"focus_details",source(s.getStepFocus()));
        if(s instanceof ActionScriptStep) {
            ActionScriptStep a=(ActionScriptStep)s;
            m.put("action",action(a.getAction()));m.put("delay_s",a.getDelayInSecs());m.put("delay_label",a.getDelayLabel());
        }
        if(s instanceof TransitionScriptStep)m.put("transition",transition(((TransitionScriptStep)s).getTransition()));
        if(s instanceof ThinkScriptStep)m.put("duration_s",((ThinkScriptStep)s).getThinkDuration());
        if(s instanceof TextActionSegment) {
            m.put("text",((TextActionSegment)s).getText());
            m.put("owner_class",s.getOwner().getClass().getName());
            m.put("owner_transition",s.getOwner() instanceof TransitionScriptStep?
                transition(((TransitionScriptStep)s.getOwner()).getTransition()):null);
            // Original TextActionSegment.getDestinationFrame uses this flag,
            // not a new inferred final-character test in the observer.
            m.put("text_segment_destination_applies",s.isInsertedByUser());
        }
        if(s instanceof TransitionDelayScriptStep) {
            TransitionDelayScriptStep delay=(TransitionDelayScriptStep)s;
            m.put("duration_s",delay.getDelayInSecs());m.put("delay_label",delay.getDelayLabel());
        }
        return m;
    }
    static List<Object> steps(Script script,Demonstration demo) throws Exception {
        List<Object> result=new ArrayList<Object>();
        for(DefaultModelGeneratorState s:script.getStepStates())result.add(map("step",step(s.getScriptStep(),demo),"state",state(s)));
        return result;
    }
    static Object design(Design d) throws Exception {
        List<Object> frames=new ArrayList<Object>();
        for(Frame f:d.getFrames()) {
            List<Object> widgets=new ArrayList<Object>(),groups=new ArrayList<Object>();
            Set<SimpleWidgetGroup> seen=Collections.newSetFromMap(new IdentityHashMap<SimpleWidgetGroup,Boolean>());
            for(IWidget w:f.getWidgets()) {
                List<Object> transitions=new ArrayList<Object>();
                for(Transition t:w.getTransitions().values())transitions.add(transition(t));
                SimpleWidgetGroup group=w.getParentGroup();
                widgets.add(map("id",id(w),"name",w.getName(),"title",w.getTitle(),"class",w.getClass().getName(),
                                "kind",String.valueOf(w.getWidgetType()),"bounds",rect(w.getEltBounds()),"level",w.getLevel(),
                                "parent",w instanceof ChildWidget?name(((ChildWidget)w).getParent()):null,
                                "group_id",id(group),"transitions_in_iteration_order",transitions));
                if(group!=null&&seen.add(group)) {
                    List<Object> members=new ArrayList<Object>();
                    for(IWidget member:group)members.add(map("id",id(member),"name",member.getName()));
                    // getName() allocates implicit Lisp symbols: observe raw stored name instead.
                    groups.add(map("id",id(group),"raw_name",field(group,"name"),"class",group.getClass().getName(),
                                   "bounds",rect(group.getEltBounds()),"members_in_iteration_order",members));
                }
            }
            List<Object> inputDevices=new ArrayList<Object>();
            for(InputDevice device:f.getInputDevices()) {
                Map<String,Object> observed=source(device);
                List<Object> transitions=new ArrayList<Object>();
                for(Transition t:device.getTransitions().values())transitions.add(transition(t));
                observed.put("transitions_in_iteration_order",transitions);inputDevices.add(observed);
            }
            frames.add(map("name",f.getName(),"widgets_in_iteration_order",widgets,"groups_in_first_widget_encounter_order",groups,
                           "input_devices_in_iteration_order",inputDevices,
                           "widget_collection_class",f.getWidgets().getClass().getName()));
        }
        List<Object> devices=new ArrayList<Object>();for(DeviceType t:d.getDeviceTypes())devices.add(t.toString());
        return map("name",d.getName(),"devices",devices,"frames_in_iteration_order",frames,
                   "frame_collection_class",d.getFrames().getClass().getName());
    }
    static void tasks(List<AUndertaking> source,List<AUndertaking> leaves) {
        for(AUndertaking t:source) {leaves.add(t);if(t instanceof TaskGroup)tasks(((TaskGroup)t).getUndertakings(),leaves);}
    }
    static Object classIdentity(Class<?> c) throws Exception {
        String resource="/"+c.getName().replace('.','/')+".class";
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        try(InputStream in=c.getResourceAsStream(resource)){byte[] buf=new byte[8192];int n;while((n=in.read(buf))!=-1)b.write(buf,0,n);}
        return map("class",c.getName(),"origin",String.valueOf(c.getProtectionDomain().getCodeSource().getLocation()),
                   "class_resource",String.valueOf(c.getResource(resource)),"sha256",digest(b.toByteArray()));
    }
    static Path originalProject(Path input,Path out) throws Exception {
        try(ZipFile z=new ZipFile(input.toFile())) {
            if(z.getEntry("PERSIST")!=null)return input;
            List<? extends ZipEntry> entries=Collections.list(z.entries());ZipEntry selected=null;
            for(ZipEntry e:entries)if(!e.isDirectory()&&e.getName().toLowerCase(Locale.ROOT).endsWith(".cgt")) {
                if(selected!=null)throw new IllegalArgumentException("ambiguous outer archive");selected=e;
            }
            if(selected==null)throw new IllegalArgumentException("no PERSIST or one original .cgt member");
            Path extracted=out.resolve("original-project.cgt");
            try(InputStream in=z.getInputStream(selected)){Files.copy(in,extracted);}
            write(out,"archive_extraction.json",map("member",selected.getName(),"sha256",digest(Files.readAllBytes(extracted))));
            return extracted;
        }
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=4)throw new IllegalArgumentException("original zip/cgt, Design::Task, config.properties, new output directory; or --synthetic spec.xml config.properties new output");
        boolean synthetic=args[0].equals("--synthetic");
        Path input=Paths.get(args[synthetic?1:0]).toAbsolutePath(),config=Paths.get(args[2]).toAbsolutePath(),out=Paths.get(args[3]).toAbsolutePath();
        if(Files.exists(out))throw new IOException("refuse existing output directory "+out);
        Files.createDirectories(out);
        Properties cfg=new Properties();try(InputStream in=Files.newInputStream(config)){cfg.load(in);}
        if(!"source_defaults".equals(cfg.getProperty("preference_policy"))||cfg.size()!=2||!cfg.containsKey("case_id"))
            throw new IllegalArgumentException("config accepts exactly preference_policy=source_defaults and case_id metadata");
        if(!SourceDefaultPreferencesFactory.class.getName().equals(System.getProperty("java.util.prefs.PreferencesFactory")))
            throw new IllegalStateException("isolated preference factory must be selected before application initialization");
        Object registration=CogToolSerialization.ONLY;
        calls.add(map("call","CogToolSerialization.ONLY","registered",registration!=null));
        Path cgt=synthetic?null:originalProject(input,out);
        Project p=synthetic?SyntheticProjectBuilder.build(input):(Project)ObjectPersister.ONLY.load(cgt.toFile());
        if(synthetic)Files.copy(input,out.resolve("synthetic_source_spec.xml"));
        else calls.add(map("call","ObjectPersister.ONLY.load","project_class",p.getClass().getName()));
        String[] selector=synthetic?new String[]{p.getDesigns().get(0).getName(),p.getUndertakings().get(0).getName()}:args[1].split("::",-1);
        if(selector.length!=2)throw new IllegalArgumentException("Design::Task required");
        Design chosen=p.getDesign(selector[0]);if(chosen==null)throw new IllegalArgumentException("unknown design");
        List<AUndertaking> all=new ArrayList<AUndertaking>();tasks(p.getUndertakings(),all);
        AUndertaking task=null;List<Object> inventory=new ArrayList<Object>();
        for(AUndertaking t:all){inventory.add(map("name",t.getName(),"class",t.getClass().getName()));
            if(t.getName().equals(selector[1])){if(task!=null)throw new IllegalArgumentException("ambiguous task");task=t;}}
        write(out,"task_inventory.json",inventory);if(task==null)throw new IllegalArgumentException("unknown task");
        TaskApplication ta=p.getTaskApplication(task,chosen);if(ta==null)throw new IllegalArgumentException("task/design has no application");
        Demonstration demo=ta.getDemonstration();
        List<Object> demonstration=new ArrayList<Object>();for(AScriptStep s:demo.getSteps())demonstration.add(step(s,demo));
        Object initial=state(demo.getInitialState());
        write(out,"original_scene.json",design(chosen));
        write(out,"original_demonstration.json",map("project",p.getName(),"saved_build_version",p.getBuildVersion(),"task",task.getName(),
                "start_frame",frameName(demo.getStartFrame()),"start_frame_chosen",demo.isStartFrameChosen(),
                "initial_state",initial,"invalid",demo.isInvalid(),"obsolete",demo.isObsolete(),"steps",demonstration));
        List<Object> cached=new ArrayList<Object>();Iterator<CognitiveModelGenerator> gens=ta.getModelGenerators();
        while(gens.hasNext()){CognitiveModelGenerator g=gens.next();cached.add(map("generator",g.getClass().getName(),"steps",steps(ta.getScript(g),demo)));}
        write(out,"cached_steps.json",cached);
        CognitiveModelGenerator gen=KLMCognitiveGenerator.ONLY;
        Script fresh=new Script(demo,gen);
        calls.add(map("call","new Script(demo, KLMCognitiveGenerator.ONLY)","constructor_initial_count",fresh.getStepStateCount(),
                       "same_as_cached",fresh==ta.getScript(gen)));
        fresh.getStepStates().clear();
        List<DefaultModelGeneratorState> generated=new ArrayList<DefaultModelGeneratorState>();
        List<String> warnings=new ArrayList<String>();
        DefaultModelGeneratorState current=gen.generateInitialSteps(demo.getStartFrame(),demo.getInitialState(),warnings,generated);
        calls.add(map("call","KLMCognitiveGenerator.generateInitialSteps","count_after",generated.size(),"state",state(current)));
        int index=0;
        for(AScriptStep original:demo.getSteps()) {
            int before=generated.size();
            current=gen.generateScriptSteps(original,current,warnings,generated);
            calls.add(map("call","KLMCognitiveGenerator.generateScriptSteps","demonstration_index",index++,
                           "input_step_id",id(original),"count_before",before,"count_after",generated.size(),"returned_state",state(current)));
        }
        fresh.getStepStates().addAll(generated);
        write(out,"fresh_steps.json",steps(fresh,demo));
        write(out,"generator_warnings.json",warnings);
        List<Object> prefs=new ArrayList<Object>();
        for(CogToolPref pref:CogToolPref.values())prefs.add(map("name",pref.name(),"key",field(pref,"key"),"kind",String.valueOf(field(pref,"kind")),
                                                              "effective",field(pref,"value"),"source_default",field(pref,"defaultValue")));
        write(out,"preferences.json",map("policy","source_defaults","host_preferences_accessed",false,"preferences",prefs));
        Path model=out.resolve("model.lisp");
        ACTR6PredictionAlgo.ONLY.outputModel(chosen,task,demo.getStartFrame(),fresh,model.toFile(),null);
        calls.add(map("call","ACTR6PredictionAlgo.ONLY.outputModel","implementation_method","ACTRPredictionAlgo.outputModel",
                       "script_is_new",fresh!=ta.getScript(gen),"complete_output_bytes",Files.size(model)));
        write(out,"call_evidence.json",calls);
        if(!json(initial).equals(json(state(demo.getInitialState()))))throw new IllegalStateException("generator mutated original initial state");
        List<Object> classes=new ArrayList<Object>();
        for(Class<?> c:new Class<?>[]{CogToolSerialization.class,ObjectPersister.class,ObjectLoader.class,Project.class,Design.class,
                Demonstration.class,Script.class,KLMCognitiveGenerator.class,ACTR6PredictionAlgo.class,ACTRPredictionAlgo.class,
                CogToolPref.class,SourceDefaultPreferencesFactory.class,JavaGenerationMain.class,org.eclipse.swt.graphics.Rectangle.class})
            classes.add(classIdentity(c));
        write(out,"class_identity.json",classes);
        write(out,"generation_record.json",map("case_id",cfg.getProperty("case_id"),"source_commit",COMMIT,
               "frontend_route",synthetic?"independent_java_synthetic_spec_builder_fresh_KLM_generator_original_ACTR_exporter":"original_java_reader_fresh_KLM_generator_original_ACTR_exporter",
               "raw_reader_shared",false,"step_generator_shared",false,"lisp_writer_shared",false,
               "high_level_spec_shared",synthetic,"official_cgt_reader_executed",!synthetic,
               "case_origin",synthetic?"synthetic":"official_original_project",
               "java_generation_executed",true,"fresh_regeneration_verified",true,
               "original_input",input.toString(),"original_input_sha256",digest(Files.readAllBytes(input)),
               "cgt_sha256",cgt==null?null:digest(Files.readAllBytes(cgt)),"selector",String.join("::",selector),"preference_policy","source_defaults",
               "model_path",model.toString(),"model_sha256",digest(Files.readAllBytes(model)),
               "frontend_patch_scope","No upstream source patches. New observer/launcher and explicit in-memory source-default preference policy.",
               "generator_call_count",index,"fresh_step_count",generated.size(),"original_demonstration_count",demo.getStepCount(),
               "cached_scripts_used_for_generation",false,"configuration_sha256",digest(Files.readAllBytes(config)),
               "migration_policy",synthetic?"Not applicable: original Java objects constructed from shared high-level specification.":"Real registered 2014 loaders executed; no harness field supplementation. Per-field migration audit separate.",
               "original_rerun_s",null,"java_version",System.getProperty("java.version"),"os_arch",System.getProperty("os.arch")));
        System.out.println("Generated "+cfg.getProperty("case_id")+" from "+(synthetic?"high-level synthetic spec":"original reader")+": "+generated.size()+" fresh states; "+model);
    }
}

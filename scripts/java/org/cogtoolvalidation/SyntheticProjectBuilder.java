package org.cogtoolvalidation;

import edu.cmu.cs.hcii.cogtool.model.*;
import edu.cmu.cs.hcii.cogtool.util.KeyboardUtil;
import java.nio.file.Path;
import java.util.*;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.*;

/** Builds original Java objects only from a declared high-level synthetic spec. */
public final class SyntheticProjectBuilder {
    static List<Element> children(Element parent, String tag) {
        List<Element> result=new ArrayList<Element>();
        for(Node n=parent.getFirstChild();n!=null;n=n.getNextSibling())
            if(n instanceof Element && (tag==null || ((Element)n).getTagName().equals(tag)))result.add((Element)n);
        return result;
    }
    static Element one(Element parent,String tag) {
        List<Element> found=children(parent,tag);
        if(found.size()!=1)throw new IllegalArgumentException("Expected one "+tag);
        return found.get(0);
    }
    static String attr(Element e,String name) {
        if(!e.hasAttribute(name)||e.getAttribute(name).isEmpty())throw new IllegalArgumentException("Missing "+e.getTagName()+"."+name);
        return e.getAttribute(name);
    }
    static void require(Element e,String name,String value) {
        if(!value.equals(attr(e,name)))throw new IllegalArgumentException("Unsupported "+e.getTagName()+"."+name);
    }
    static double number(Element e,String name) {
        double value=Double.parseDouble(attr(e,name));
        if(Double.isNaN(value)||Double.isInfinite(value))throw new IllegalArgumentException("Nonfinite "+name);
        return value;
    }
    static HandLocation hand(String value) {
        if(value.equals("mouse"))return HandLocation.OnMouse;
        if(value.equals("keyboard"))return HandLocation.OnKeyboard;
        throw new IllegalArgumentException("Unsupported hand location "+value);
    }
    public static Project build(Path spec) throws Exception {
        // The frozen upstream classpath also contains an obsolete Xerces JAXP
        // provider. Select the real current JDK DOM provider for this new spec
        // reader only; the original .cgt reader retains its original provider.
        DocumentBuilderFactory f=DocumentBuilderFactory.newInstance(
            "com.sun.org.apache.xerces.internal.jaxp.DocumentBuilderFactoryImpl",null);
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl",true);
        f.setFeature("http://xml.org/sax/features/external-general-entities",false);
        f.setFeature("http://xml.org/sax/features/external-parameter-entities",false);
        f.setXIncludeAware(false);f.setExpandEntityReferences(false);
        Element root=f.newDocumentBuilder().parse(spec.toFile()).getDocumentElement();
        if(!root.getTagName().equals("synthetic-spec"))throw new IllegalArgumentException("Wrong spec root");
        require(root,"schema_version","1");require(root,"origin","synthetic");
        Element designSpec=one(root,"design");require(designSpec,"devices","mouse keyboard");
        Set<DeviceType> devices=new LinkedHashSet<DeviceType>();
        devices.add(DeviceType.Mouse);devices.add(DeviceType.Keyboard);
        Project project=new Project("Synthetic "+attr(root,"id"));
        Design design=new Design(attr(designSpec,"name"),devices);
        project.addDesign(design);
        Map<String,Frame> frames=new LinkedHashMap<String,Frame>();
        Map<String,Map<String,IWidget>> widgets=new LinkedHashMap<String,Map<String,IWidget>>();
        Map<String,Map<String,InputDevice>> inputDevices=new LinkedHashMap<String,Map<String,InputDevice>>();
        for(Element fs:children(designSpec,"frame")) {
            String frameId=attr(fs,"id");
            if(frames.containsKey(frameId))throw new IllegalArgumentException("Duplicate frame ID");
            Frame frame=new Frame(attr(fs,"name"),devices);design.addFrame(frame);frames.put(frameId,frame);
            Map<String,IWidget> local=new LinkedHashMap<String,IWidget>();widgets.put(frameId,local);
            Map<String,InputDevice> localDevices=new LinkedHashMap<String,InputDevice>();inputDevices.put(frameId,localDevices);
            List<Element> declaredDevices=children(fs,"device");
            if(declaredDevices.isEmpty())localDevices.put("keyboard",frame.getInputDevice(DeviceType.Keyboard));
            for(Element ds:declaredDevices) {
                require(ds,"kind","keyboard");String deviceId=attr(ds,"id");
                InputDevice device=frame.getInputDevice(DeviceType.Keyboard);
                if(device==null||!attr(ds,"name").equals(device.getName()))throw new IllegalArgumentException("Device declaration differs from original Frame device");
                if(!localDevices.isEmpty())throw new IllegalArgumentException("Only one original Keyboard device exists per frame");
                localDevices.put(deviceId,device);
            }
            for(Element ws:children(fs,"widget")) {
                String kind=attr(ws,"kind");
                WidgetType widgetType=kind.equals("button")?WidgetType.Button:kind.equals("text")?WidgetType.Text:null;
                if(widgetType==null)throw new IllegalArgumentException("Unsupported widget kind "+kind);
                String widgetId=attr(ws,"id");
                if(local.containsKey(widgetId))throw new IllegalArgumentException("Duplicate widget ID");
                double width=number(ws,"width"),height=number(ws,"height");
                if(width<1||height<1)throw new IllegalArgumentException("Spec geometry must not trigger Java minimum-size adjustment");
                Widget widget=new Widget(new DoubleRectangle(number(ws,"x"),number(ws,"y"),width,height),widgetType);
                widget.setName(attr(ws,"name"));widget.setTitle(attr(ws,"title"));frame.addWidget(widget);local.put(widgetId,widget);
            }
        }
        Element ts=one(root,"task");require(ts,"mouse_hand","right");
        Task task=new Task(attr(ts,"name"));project.addUndertaking(task);
        TaskApplication app=new TaskApplication(task,design);project.setTaskApplication(app);
        Demonstration demo=app.getDemonstration();
        Frame start=frames.get(attr(ts,"start_frame"));if(start==null)throw new IllegalArgumentException("Missing start frame");
        demo.setStartFrame(start);demo.setStartFrameChosen(true);demo.setMouseHand(HandLocation.RIGHT_HAND);
        demo.getInitialState().setHandLocation(HandLocation.LEFT_HAND,hand(attr(ts,"left_hand")));
        demo.getInitialState().setHandLocation(HandLocation.RIGHT_HAND,hand(attr(ts,"right_hand")));
        Frame current=start;int index=0;
        for(Element step:children(one(ts,"demonstration"),null)) {
            String frameId=attr(step,"frame");Frame frame=frames.get(frameId);
            if(frame==null||frame!=current)throw new IllegalArgumentException("Demonstration frame disagrees with prior destination");
            if(step.getTagName().equals("look")) {
                IWidget target=widgets.get(frameId).get(attr(step,"target"));
                if(target==null||target.getFrame()!=frame)throw new IllegalArgumentException("Unknown or wrongly owned look target");
                demo.appendStep(new LookAtScriptStep(target));
                JavaGenerationMain.calls.add(JavaGenerationMain.map("call","new LookAtScriptStep(IWidget); demo.appendStep",
                    "spec_demonstration_index",index,"target",target.getName(),"frame",frame.getName(),
                    "widget_type",String.valueOf(target.getWidgetType()),"synthetic_duration_supplied",false));
            } else if(step.getTagName().equals("type")) {
                String command=attr(step,"is_command");
                if(!command.equals("true")&&!command.equals("false"))throw new IllegalArgumentException("is_command must be true or false");
                require(step,"modifiers","0");require(step,"focus","keyboard_device");
                String text=attr(step,"text");
                if(!text.matches("[a-z0-9"+KeyboardUtil.DOWN_ARROW_CHAR+"]+"))
                    throw new IllegalArgumentException("Synthetic key scope is lowercase letters, digits and original DOWN_ARROW_CHAR only");
                String deviceId=step.hasAttribute("device_id")?attr(step,"device_id"):"keyboard";
                InputDevice device=inputDevices.get(frameId).get(deviceId);
                if(device==null||device.getFrame()!=frame)throw new IllegalArgumentException("Unknown or wrongly owned keyboard device");
                KeyAction action=new KeyAction(text,Boolean.parseBoolean(command),0);
                if(!device.canAccept(action))throw new IllegalArgumentException("Original InputDevice refuses this action");
                if(step.hasAttribute("destination")) {
                    Frame destination=frames.get(attr(step,"destination"));
                    if(destination==null)throw new IllegalArgumentException("Unknown keyboard destination");
                    double delay=number(step,"delay_s");if(delay<0)throw new IllegalArgumentException("Negative delay");
                    String label=attr(step,"delay_label");
                    Transition transition=new Transition(device,destination,action);transition.setDelayInfo(delay,label);
                    device.addTransition(transition);demo.appendStep(new TransitionScriptStep(transition));current=destination;
                    JavaGenerationMain.calls.add(JavaGenerationMain.map("call","new KeyAction(String,isCommand,0); InputDevice.canAccept; new Transition(InputDevice,...); device.addTransition; new TransitionScriptStep; demo.appendStep",
                        "spec_demonstration_index",index,"text",text,"is_command",action.isCommand(),"modifiers",action.getModifiers(),
                        "device_id",deviceId,"device_class",device.getClass().getName(),"frame",frame.getName(),"destination",destination.getName(),"delay_s",delay));
                } else {
                    if(step.hasAttribute("delay_s")||step.hasAttribute("delay_label"))throw new IllegalArgumentException("Device action delay requires a declared transition");
                    demo.appendStep(new ActionScriptStep(action,device));
                    JavaGenerationMain.calls.add(JavaGenerationMain.map("call","new KeyAction(String,isCommand,0); InputDevice.canAccept; new ActionScriptStep; demo.appendStep",
                        "spec_demonstration_index",index,"text",text,"is_command",action.isCommand(),"modifiers",action.getModifiers(),
                        "device_id",deviceId,"device_class",device.getClass().getName(),"frame",frame.getName()));
                }
            } else if(step.getTagName().equals("click")) {
                require(step,"button","left");require(step,"press","click");require(step,"modifiers","0");
                IWidget target=widgets.get(frameId).get(attr(step,"target"));
                Frame destination=frames.get(attr(step,"destination"));
                if(target==null||destination==null)throw new IllegalArgumentException("Unknown click target/destination");
                double delay=number(step,"delay_s");if(delay<0)throw new IllegalArgumentException("Negative delay");
                ButtonAction action=new ButtonAction(MouseButtonState.Left,MousePressType.Click,0);
                String label=step.hasAttribute("delay_label")?step.getAttribute("delay_label"):"synthetic response";
                Transition transition=new Transition(target,destination,action);transition.setDelayInfo(delay,label);
                target.addTransition(transition);demo.appendStep(new TransitionScriptStep(transition));current=destination;
                JavaGenerationMain.calls.add(JavaGenerationMain.map("call","new ButtonAction; new Transition; setDelayInfo; new TransitionScriptStep; demo.appendStep",
                    "spec_demonstration_index",index,"target",target.getName(),"frame",frame.getName(),"destination",destination.getName(),"delay_s",delay));
            } else throw new IllegalArgumentException("Unsupported synthetic demonstration "+step.getTagName());
            index++;
        }
        JavaGenerationMain.calls.add(JavaGenerationMain.map("call","SyntheticProjectBuilder.build","high_level_spec_shared",true,
            "generated_steps_supplied",false,"production_or_event_times_supplied",false,"frame_count",frames.size(),"demonstration_count",index));
        return project;
    }
}

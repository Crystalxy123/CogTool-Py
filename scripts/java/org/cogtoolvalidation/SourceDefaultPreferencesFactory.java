package org.cogtoolvalidation;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.prefs.AbstractPreferences;
import java.util.prefs.Preferences;
import java.util.prefs.PreferencesFactory;

/** Explicit source-default preference policy; never reads or writes host prefs. */
public final class SourceDefaultPreferencesFactory implements PreferencesFactory {
    private static final class Node extends AbstractPreferences {
        private final Map<String, String> values = new LinkedHashMap<String, String>();
        private final Map<String, Node> children = new LinkedHashMap<String, Node>();
        Node(AbstractPreferences parent, String name) { super(parent, name); }
        protected void putSpi(String key, String value) { values.put(key, value); }
        protected String getSpi(String key) { return values.get(key); }
        protected void removeSpi(String key) { values.remove(key); }
        protected void removeNodeSpi() { values.clear(); children.clear(); }
        protected String[] keysSpi() { return values.keySet().toArray(new String[0]); }
        protected String[] childrenNamesSpi() { return children.keySet().toArray(new String[0]); }
        protected AbstractPreferences childSpi(String name) {
            Node result = children.get(name);
            if (result == null) { result = new Node(this, name); children.put(name, result); }
            return result;
        }
        protected void syncSpi() {}
        protected void flushSpi() {}
    }
    private final Preferences user = new Node(null, "");
    private final Preferences system = new Node(null, "");
    public Preferences userRoot() { return user; }
    public Preferences systemRoot() { return system; }
}

"""
A small, strict stand-in for the Streamlit runtime used to execute app.py
headlessly (the build sandbox has no PyPI access). It reproduces the semantics
that matter for correctness:

* the script re-runs top to bottom on every interaction (runpy)
* widget values live in session_state; widgets not rendered in a run lose state
* callbacks (on_click / on_change) run before the next script run
* modifying a widget's key after it was instantiated raises (like Streamlit)
* duplicate widget keys raise
* st.rerun() / st.stop() control flow
"""

import contextlib
import functools
import runpy
import sys
import types


class RerunException(Exception):
    pass


class StopException(Exception):
    pass


class StreamlitAPIException(Exception):
    pass


class SessionState:
    def __init__(self, h):
        object.__setattr__(self, "_d", {})
        object.__setattr__(self, "_h", h)

    def __getattr__(self, k):
        try:
            return self._d[k]
        except KeyError:
            raise AttributeError(f"st.session_state has no attribute '{k}'")

    def __setattr__(self, k, v):
        self[k] = v

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        h = self._h
        if k in h.rendered and k in h.widget_ids and not h.in_callback:
            raise StreamlitAPIException(f"st.session_state.{k} cannot be modified after the widget with key {k} is instantiated.")
        self._d[k] = v

    def __delitem__(self, k):
        del self._d[k]

    def __contains__(self, k):
        return k in self._d

    def __iter__(self):
        return iter(list(self._d))

    def keys(self):
        return list(self._d.keys())

    def get(self, k, d=None):
        return self._d.get(k, d)

    def pop(self, k, *d):
        return self._d.pop(k, *d)


class FakeUploadedFile:
    def __init__(self, name, data: bytes):
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self):
        return self._data


class Harness:
    def __init__(self):
        self.state = SessionState(self)
        self.widget_ids = set()
        self.callbacks = {}
        self.rendered = set()
        self.out = []
        self.in_callback = False
        self.clicked = set()
        self.chat_value = None
        self.runs = 0

    # ------------------------------------------------------------------
    def widget(self, kind, label, key, default, on_change=None, args=(), kwargs=None, options=None):
        wid = key or f"{kind}:{label}"
        if wid in self.rendered:
            raise StreamlitAPIException(f"Duplicate widget id: {wid}")
        self.rendered.add(wid)
        self.widget_ids.add(wid)
        if on_change:
            self.callbacks[wid] = (on_change, args or (), kwargs or {})
        else:
            self.callbacks.pop(wid, None)
        if wid not in self.state._d:
            self.state._d[wid] = default
        val = self.state._d[wid]
        if options is not None and val not in options and kind in ("selectbox", "radio"):
            raise StreamlitAPIException(f"{kind} {wid}: session value {val!r} not in options")
        return val

    def button(self, kind, label, key, on_click=None, args=(), kwargs=None, disabled=False):
        wid = key or f"{kind}:{label}"
        if wid in self.rendered:
            raise StreamlitAPIException(f"Duplicate widget id: {wid}")
        self.rendered.add(wid)
        if on_click:
            self.callbacks[wid] = (on_click, args or (), kwargs or {})
        return (wid in self.clicked) and not disabled

    def emit(self, kind, *payload):
        self.out.append((kind,) + tuple(payload))

    def text(self):
        return "\n".join(str(p) for o in self.out for p in o[1:] if isinstance(p, str))

    # ------------------------------------------------------------------
    def run(self, path, clicks=(), changes=None, chat=None):
        changes = changes or {}
        for wid, val in changes.items():
            self.state._d[wid] = val
        self.in_callback = True
        try:
            for wid in list(changes) + list(clicks):
                cb = self.callbacks.get(wid)
                if cb:
                    cb[0](*cb[1], **cb[2])
        finally:
            self.in_callback = False
        self.clicked = set(clicks)
        self.chat_value = chat
        for _ in range(8):
            self.rendered = set()
            self.out = []
            self.runs += 1
            try:
                runpy.run_path(path, run_name="__main__")
                result = "ok"
            except RerunException:
                self._cleanup()
                self.clicked = set()
                self.chat_value = None
                continue
            except StopException:
                result = "stop"
            self._cleanup()
            self.clicked = set()
            self.chat_value = None
            return result
        raise RuntimeError("Too many reruns")

    def _cleanup(self):
        for wid in list(self.widget_ids):
            if wid not in self.rendered:
                self.state._d.pop(wid, None)
                self.callbacks.pop(wid, None)


H = Harness()


class DG:
    """Delta generator: every layout object exposes the full API."""

    def __init__(self, name="main"):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    # output
    def markdown(self, body, unsafe_allow_html=False, **k):
        H.emit("markdown", body)

    def write(self, *a, **k):
        H.emit("write", *[str(x) for x in a])

    def caption(self, body, **k):
        H.emit("caption", body)

    def code(self, body, language=None, **k):
        H.emit("code", body, language or "")

    def json(self, body, **k):
        H.emit("json", str(body))

    def error(self, body, **k):
        H.emit("error", str(body))

    def warning(self, body, **k):
        H.emit("warning", str(body))

    def info(self, body, **k):
        H.emit("info", str(body))

    def success(self, body, **k):
        H.emit("success", str(body))

    def divider(self):
        H.emit("divider")

    title = header = subheader = markdown

    # widgets
    def button(self, label, key=None, on_click=None, args=None, kwargs=None, disabled=False, **k):
        return H.button("button", label, key, on_click, args, kwargs, disabled)

    def download_button(self, label, data, key=None, on_click=None, args=None, kwargs=None, **k):
        assert isinstance(data, (str, bytes)), "download data must be str/bytes"
        return H.button("download_button", label, key, on_click, args, kwargs)

    def form_submit_button(self, label="Submit", key=None, on_click=None, args=None, kwargs=None, **k):
        return H.button("form_submit_button", label, key, on_click, args, kwargs)

    def checkbox(self, label, value=False, key=None, on_change=None, args=None, kwargs=None, **k):
        return H.widget("checkbox", label, key, value, on_change, args, kwargs)

    toggle = checkbox

    def radio(self, label, options, index=0, key=None, on_change=None, args=None, kwargs=None, **k):
        options = list(options)
        return H.widget("radio", label, key, options[index] if options else None, on_change, args, kwargs, options)

    def selectbox(self, label, options, index=0, key=None, on_change=None, args=None, kwargs=None, format_func=str, **k):
        options = list(options)
        for o in options:
            format_func(o)  # make sure the formatter never crashes
        return H.widget("selectbox", label, key, options[index] if options else None, on_change, args, kwargs, options)

    def multiselect(self, label, options, default=None, key=None, on_change=None, **k):
        return H.widget("multiselect", label, key, list(default or []), on_change)

    def pills(self, label, options, selection_mode="single", default=None, key=None, on_change=None, **k):
        return H.widget("pills", label, key, list(default or []) if selection_mode == "multi" else default, on_change)

    def text_input(self, label, value="", key=None, on_change=None, args=None, kwargs=None, **k):
        return H.widget("text_input", label, key, value, on_change, args, kwargs)

    def file_uploader(self, label, type=None, key=None, on_change=None, args=None, kwargs=None, **k):
        return H.widget("file_uploader", label, key, None, on_change, args, kwargs)

    def chat_input(self, placeholder="", key=None, disabled=False, **k):
        wid = key or "chat_input"
        H.rendered.add(wid)
        return None if disabled else H.chat_value

    # layout
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [DG(f"col{i}") for i in range(n)]

    def container(self, **k):
        return DG("container")

    def expander(self, label, **k):
        return DG("expander")

    def tabs(self, labels):
        return [DG(f"tab:{l}") for l in labels]

    def form(self, key, **k):
        return DG("form")

    def chat_message(self, name, **k):
        H.emit("chat_message", name)
        return DG("chat")

    def empty(self):
        return DG("empty")


_root = DG()
st = types.ModuleType("streamlit")
for _name in dir(DG):
    if not _name.startswith("_"):
        setattr(st, _name, getattr(_root, _name))
st.sidebar = DG("sidebar")
st.session_state = H.state


@contextlib.contextmanager
def _spinner(text="", **k):
    H.emit("spinner", text)
    yield


st.spinner = _spinner
st.set_page_config = lambda **k: H.emit("page_config", str(k))
st.toast = lambda body, icon=None, **k: H.emit("toast", str(body))


def _rerun(**k):
    if H.in_callback:
        return
    raise RerunException()


def _stop():
    raise StopException()


st.rerun = _rerun
st.stop = _stop
st.context = types.SimpleNamespace(timezone="America/New_York")


_CACHES = {}


def _cache(func=None, **opts):
    def deco(f):
        # Like Streamlit: the cache survives reruns (keyed by function identity + source).
        memo = _CACHES.setdefault((f.__qualname__, f.__code__.co_code), {})

        @functools.wraps(f)
        def wrapper(*a, **kw):
            names = f.__code__.co_varnames[: f.__code__.co_argcount]
            key = tuple(v for n, v in zip(names, a) if not n.startswith("_")) + tuple(sorted((k, v) for k, v in kw.items() if not k.startswith("_")))
            if key not in memo:
                memo[key] = f(*a, **kw)
            return memo[key]

        wrapper.clear = memo.clear
        return wrapper

    return deco(func) if callable(func) else deco


st.cache_resource = _cache
st.cache_data = _cache
st.__harness__ = H
sys.modules["streamlit"] = st

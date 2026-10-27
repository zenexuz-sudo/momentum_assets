"""One look shared by a few tools' windows, MomentumAssets' among them.

Plain tkinter with no imports from any one tool, so each can copy this file as it is.
"""

import tkinter as tk

# ---- colours ----
BG = "#080808"
LINE = "#1a1a1a"          # dividers, and the mode strip when idle
TEXT = "#e0e0e0"          # values
LABEL = "#555555"         # labels next to values
FAINT = "#3a3a3a"         # the title, the [X] at rest
KEY = "#9a9a9a"           # key names in the legend
KEY_ACTION = "#4a4a4a"    # what each key does

CYAN = "#00e5ff"          # playing back / information
RED = "#ff3366"           # recording / live
GREEN = "#00ff7f"         # ready
GOOD = "#00d26a"          # MEM OK
BAD = "#ff3333"           # NO MEM, and the [X] under the mouse

# ---- type ----
FONT = "Consolas"
# The title is the one proportional face: in Consolas a narrow letter takes a whole cell, so
# tool names of different lengths come out looking differently spaced next to each other.
TITLE_FONT = "Segoe UI Semibold"
TITLE = (TITLE_FONT, 9)
STATUS = (FONT, 13, "bold")
BODY = (FONT, 9)
VALUE = (FONT, 9, "bold")
SMALL = (FONT, 8)
SMALL_BOLD = (FONT, 8, "bold")

# Which look the settings windows are drawn in. "new": plain words, the font's arrows and
# drawn - and +, steppers in line with the name box, a line under it. "classic": the first look
# - everything in brackets, narrow steppers, two lines over the message - with the same
# spacing. The bars and debug windows are the same in both. A tool sets this from its saved
# settings before it opens a settings window; only its debug window changes it.
LOOKS = ("new", "classic")
LOOK = "new"

WIDTH = 320               # logical pixels
PAD = 10                  # left/right margin for everything


def window(title, x=30, y=30, alpha=0.93, parent=None):
    """A borderless, always-on-top, see-through window. Give it a parent for a second window
    that belongs to the first, such as a settings window."""
    root = tk.Tk() if parent is None else tk.Toplevel(parent)
    root.title(title)
    root.overrideredirect(True)
    root.attributes("-topmost", True, "-alpha", alpha)
    root.configure(bg=BG)
    root.geometry(f"+{x}+{y}")
    return root


def draggable(root, *widgets):
    """Dragging any of `widgets` moves the window."""
    grab = {}

    def start(e):
        grab["x"], grab["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        root.geometry(f"+{e.x_root - grab['x']}+{e.y_root - grab['y']}")

    for w in widgets:
        w.bind("<Button-1>", start, add="+")
        w.bind("<B1-Motion>", move, add="+")


def title_bar(root, name, on_close, buttons=()):
    """Mode strip, the tool's name top left, and an [X] that lights up red under the mouse.
    `buttons` are (word, command) pairs, shown in order to the left of the [X].

    Returns the strip; colour it with the current mode. `strip.note` is a label beside the
    name, empty until there's something to say - a word in red when something is wrong."""
    strip = tk.Frame(root, bg=LINE, height=2)
    strip.pack(fill="x")
    bar = tk.Frame(root, bg=BG)
    # 8, not PAD: [X]'s bracket then ends on the same pixel column as the rows under it
    bar.pack(fill="x", padx=(PAD, 8), pady=(4, 0))
    title = tk.Label(bar, text=name, fg=FAINT, bg=BG, font=TITLE)
    title.pack(side="left")
    strip.note = tk.Label(bar, text="", fg=BAD, bg=BG, font=SMALL_BOLD)
    strip.note.pack(side="left", padx=(10, 0))
    close = button(bar, "X", on_close, rest=FAINT, hover=BAD, font=(FONT, 9, "bold"))
    close.pack(side="right")
    for word, command in reversed(buttons):
        button(bar, word, command, rest=FAINT, font=(FONT, 9, "bold")).pack(side="right",
                                                                           padx=(0, 8))
    draggable(root, strip, bar, title, strip.note)
    return strip


def quiet(hover=False):
    """The grey of a switch that's off: faint, and a little brighter under the mouse."""
    return KEY if hover else FAINT


def button(parent, word, command, rest=KEY, hover=CYAN, font=SMALL_BOLD, brackets=True,
           flush=None):
    """A word that does something when clicked, and lights up under the mouse. In brackets,
    [LIKE THIS], for a button that opens or closes a window - SETTINGS, DEBUG, X. `flush` (the
    default without brackets): its letters reach its edges, so it lines up with what's above
    it, and a little room above and below makes it easy to hit. Returns the label, not yet
    placed. enable(label, False) greys it out and stops it doing anything, for a setting that
    doesn't apply just now."""
    text = f"[{word}]" if brackets else word
    pads = dict(bd=0, padx=0, pady=2) if (not brackets if flush is None else flush) else {}
    label = tk.Label(parent, text=text, fg=rest, bg=BG, font=font, cursor="hand2", **pads)
    label.rest, label.hover, label.enabled, label.over = rest, hover, True, False
    label.command = command
    label.bind("<Button-1>", lambda _e: click(label))
    label.bind("<Enter>", lambda _e: mouse_over(label, True))
    label.bind("<Leave>", lambda _e: mouse_over(label, False))
    return label


def word(parent, text, command):
    """Something you do in a window - COPY, DELETE, NEW: the plain word in the new look, in
    brackets in the classic one, and flush either way. Returns the label, not yet placed."""
    return button(parent, text, command, brackets=LOOK == "classic", flush=True)


def click(label):
    """What clicking a button() does - out here so a test can click one without a mouse."""
    if label.enabled:
        label.command()


def mouse_over(label, over):
    """The mouse coming onto a button() or an arrow(), or leaving it."""
    label.over = over
    if label.enabled:
        _paint(label, label.hover if over else label.rest)


def _paint(widget, colour):
    """A button's colour: its text's, or an arrow's shape's."""
    paint = widget.__dict__.get("paint")
    if paint:
        paint(colour)
    else:
        widget.config(fg=colour)


# The classic look's steppers, in both tools: the longest value either steps through and a
# space, with no padding of its own. That makes the column, [ to ], 112 px of the 293 between
# the margins' letters: 0.382, 1/phi^2, as near as whole pixels go.
STEPPER_LETTERS = len("0.5 UNITS") + 1
ARROW_BOX = 14            # the square a stepper's button sits in, and is clicked in
ARROW_GAP = 4             # between a stepper's buttons and the box or value between them
POINTERS = {"<": "\u25c4", ">": "\u25ba"}


def arrow(parent, way, command):
    """A stepper's button: < or > to pick from a list, - or + to set an amount. Grey, cyan
    under the mouse, faint when it can't go further. Returns the widget, not yet placed.

    < and > are Consolas's own pointers, 7 pixels wide; - and + are drawn, 8 across with
    2-pixel strokes. Each sits in the same square, placed so a column of them shares its outer
    edge: a > ends on the same pixel as a +, and a < starts on the same pixel as a -.

    In the classic look it's the first one's [<], [>], [-] or [+]."""
    if LOOK == "classic":
        label = button(parent, way, command, flush=True)
        label.config(padx=2)                # so [>] and [+] end on the shared right edge
        return label
    widget = tk.Canvas(parent, width=ARROW_BOX, height=ARROW_BOX, bg=BG, highlightthickness=0,
                       cursor="hand2")
    if way in POINTERS:
        # a pointer's ink is centred on where it's put: from 3 for <, to 10 for >
        widget.create_text(6 if way == "<" else 7, ARROW_BOX // 2, text=POINTERS[way],
                           fill=KEY, font=VALUE, tags="shape")
    else:
        widget.create_rectangle(3, 6, 11, 8, fill=KEY, outline="", tags="shape")
        if way == "+":
            widget.create_rectangle(6, 3, 8, 11, fill=KEY, outline="", tags="shape")
    widget.paint = lambda colour: widget.itemconfig("shape", fill=colour)
    widget.rest, widget.hover, widget.enabled, widget.over = KEY, CYAN, True, False
    widget.command = command
    widget.bind("<Button-1>", lambda _e: click(widget))
    widget.bind("<Enter>", lambda _e: mouse_over(widget, True))
    widget.bind("<Leave>", lambda _e: mouse_over(widget, False))
    return widget


def name_box(block, box, back, on):
    """< box > at the right of `block`, a frame laid out with grid that has the name in
    column 0 - a profile's, say, or a run's. Under the box, a frame for the words that
    act on what's in it: put them there with under_box(). In the new look it's exactly as wide
    as the box; in the classic one it spans the classic steppers' column below, from their
    [<] to the window's right edge. Returns that frame."""
    block.columnconfigure(0, weight=1)
    arrow(block, "<", back).grid(row=0, column=1)
    box.grid(row=0, column=2, padx=ARROW_GAP)
    arrow(block, ">", on).grid(row=0, column=3)
    under = tk.Frame(block, bg=BG)
    if LOOK == "classic":
        # from the steppers' [<] or [-] to the window's right edge, where [DELETE]'s bracket
        # ends on the same pixel as [>], [+] and [X]; its width fixed, so CONFIRM? moves
        # nothing, and free to reach left of the box, so it never widens it
        probe = [arrow(block, "<", None),
                 tk.Label(block, font=VALUE, width=STEPPER_LETTERS, padx=0),
                 arrow(block, ">", None)]
        width = sum(w.winfo_reqwidth() for w in probe) - 4     # inside the [ and ]'s 2 px
        for w in probe:
            w.destroy()
        under.config(width=width)
        under.pack_propagate(False)
        under.grid(row=1, column=0, columnspan=4, sticky="e", padx=(0, 2), pady=(4, 0))
    else:
        under.grid(row=1, column=2, sticky="ew", padx=ARROW_GAP, pady=(4, 0))
    return under


def under_box(first, last):
    """The words under a name box, in name_box()'s frame. In the new look the first goes
    against the box's left edge and the last against its right; in the classic look they sit
    side by side on the window's right edge, under the [>]. Either way a CONFIRM? has room to
    grow into without moving anything: in the classic look the frame's width is fixed, the
    first word starts in line with the steppers' [<] below and the last ends on the window's
    right edge, and each grows into the space between them."""
    if LOOK == "classic":
        first.pack(side="left")
        last.config(width=len(Confirm.WORD) + 2, anchor="e")
        last.pack(side="right")
        first.master.config(height=max(first.winfo_reqheight(), last.winfo_reqheight()))
    else:
        first.pack(side="left")
        last.pack(side="right")


def selector_rule(root):
    """Under the run or profile selector: a line in the new look; the classic look keeps the
    space, without the line."""
    divider(root, above=5, hidden=LOOK == "classic")


def rule_over_message(root):
    """Over a settings window's message line: one line in the new look, two in the classic
    one (it had a rule under its pages, then the message's own)."""
    if LOOK == "classic":
        divider(root, above=4, below=0)
        divider(root, above=6, below=4)
    else:
        divider(root, above=4, below=4)


def stepper(row, back, on, box, down="<", up=">", pady=0):
    """< value > at the right of `row` (or - value +, for an amount). In the new look the value
    is centred in a field as wide as `box`, the name box, so every stepper's buttons sit in
    line with the name box's arrows, down the whole window. In the classic look it's
    STEPPER_LETTERS
    wide, the longest value and a space, so steppers line up with each other. Returns the
    value's label and the two buttons."""
    after = arrow(row, up, on)
    after.pack(side="right", pady=pady)
    if LOOK == "classic":
        value = tk.Label(row, text="", fg=TEXT, bg=BG, font=VALUE, width=STEPPER_LETTERS,
                         padx=0)
        value.pack(side="right", pady=pady)
        before = arrow(row, down, back)
        before.pack(side="right", pady=pady)
        return value, before, after
    width = box.winfo_reqwidth()
    field = tk.Frame(row, width=width, bg=BG)
    value = tk.Label(field, text="", fg=TEXT, bg=BG, font=VALUE)
    value.place(relx=0.5, rely=0.5, anchor="center")
    field.config(height=value.winfo_reqheight())
    field.pack(side="right", padx=ARROW_GAP, pady=pady)
    before = arrow(row, down, back)
    before.pack(side="right", pady=pady)
    return value, before, after


class Confirm:
    """A word button for something you'd rather not do by mistake - deleting a profile or a
    run, starting a new run. The first click only asks: the word becomes a red CONFIRM? for
    three seconds, and a click on that does it. One asks at a time, and anything that changes
    what it would act on - another profile or run picked - should cancel_asking() first.

    `first`, if given, is asked before asking: False means not now (it says why), so a click
    that can't come to anything doesn't ask. `label` is the widget, not yet placed: under_box()
    leaves it room to grow into, so CONFIRM? moves nothing beside it. In the classic look it's
    [CONFIRM?]."""

    WORD = "CONFIRM?"
    SECONDS = 3
    _asking = None                          # the one waiting for its second click

    def __init__(self, parent, word, command, first=None):
        self.word, self.command, self.first, self._timer = word, command, first, None
        self.brackets = LOOK == "classic"
        self.label = button(parent, word, self._click, brackets=self.brackets, flush=True)

    @property
    def asking(self):
        return self._timer is not None

    @classmethod
    def cancel_asking(cls):
        if cls._asking is not None:
            cls._asking.cancel()

    def _click(self):
        if self.asking:
            self.cancel()
            self.command()
            return
        if self.first is not None and not self.first():
            return
        Confirm.cancel_asking()
        Confirm._asking = self
        self._timer = self.label.after(int(self.SECONDS * 1000), self.cancel)
        self._look(self.WORD, RED, RED)

    def cancel(self):
        if Confirm._asking is self:
            Confirm._asking = None
        timer, self._timer = self._timer, None
        try:
            if timer is not None:
                self.label.after_cancel(timer)
            self._look(self.word, KEY, CYAN)
        except tk.TclError:                 # its window has closed
            pass

    def _look(self, word, rest, hover):
        label = self.label
        label.rest, label.hover = rest, hover
        update(label, text=f"[{word}]" if self.brackets else word,
               fg=hover if label.over else rest)


def update(widget, **options):
    """widget.config(**options), but only what's changed. A HUD refreshes ten times a second,
    and having Tk redo every widget each time, changed or not, cost one tool's bar 3.6% of a
    core sitting still. Once a widget goes through here, set it only through here."""
    shown = widget.__dict__.setdefault("_shown_options", {})
    changed = {k: v for k, v in options.items() if shown.get(k, shown) != v}
    if changed:
        widget.config(**changed)
        shown.update(changed)


def enable(button_label, on):
    """Switch a button() or an arrow() on or off. Off, it's faint and clicking it does
    nothing."""
    button_label.enabled = bool(on)
    colour, cursor = (button_label.rest if on else FAINT), ("hand2" if on else "")
    if "paint" in button_label.__dict__:
        if button_label.__dict__.get("_shown") != (colour, cursor):    # ten times a second
            button_label.paint(colour)
            button_label.config(cursor=cursor)
            button_label._shown = (colour, cursor)
    else:
        update(button_label, fg=colour, cursor=cursor)


class Tabs:
    """Pages of one window, and a row of their names to switch between them. For a settings
    window with more in it than fits on a screen.

    `words` name the pages, in order. page(word) is the frame to build that page in. Call
    settle() once they're all built: it gives every page the height of the tallest, so the
    window doesn't jump when you switch."""

    def __init__(self, root, words):
        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", padx=PAD, pady=(1, 0))
        divider(root, above=4, below=3)           # between the tabs and their pages
        self.holder = tk.Frame(root, bg=BG)
        self.holder.pack(fill="x")
        self.labels, self.pages, self.showing, self.hover = {}, {}, None, None
        for word in words:
            # 9 pt like the window's rows, a size up from its COPY and DELETE, so tabs and
            # actions never look alike; 14 apart, which leaves 21 between their letters
            label = tk.Label(row, text=word, bg=BG, font=VALUE, cursor="hand2")
            label.pack(side="left", padx=(0, 14))
            label.bind("<Button-1>", lambda _e, w=word: self.show(w))
            label.bind("<Enter>", lambda _e, w=word: self._hovering(w))
            label.bind("<Leave>", lambda _e: self._hovering(None))
            self.labels[word] = label
            self.pages[word] = tk.Frame(self.holder, bg=BG)
        self.show(words[0])

    def page(self, word):
        return self.pages[word]

    def show(self, word):
        if self.showing:
            self.pages[self.showing].pack_forget()
        self.showing = word
        self.pages[word].pack(fill="x")
        self._draw()

    def settle(self):
        self.holder.update_idletasks()
        tallest = max(page.winfo_reqheight() for page in self.pages.values())
        self.holder.pack_propagate(False)
        self.holder.config(height=tallest)

    def _hovering(self, word):
        self.hover = word
        self._draw()

    def _draw(self):
        for word, label in self.labels.items():
            label.config(fg=CYAN if word == self.showing else (TEXT if word == self.hover else KEY))


class Checkbox:
    """A box and a line of text on their own row; click either to tick or untick it. `detail`
    is a few quiet words after the text, saying what it is. With `side`, it goes at that side
    of a row of your own instead - on the same line as a name, say.

    `on_change(ticked)` is called after a click. set() changes it without calling that, and
    enable(False) greys it out for a setting that doesn't apply just now, as Choice's does."""

    SIZE = 11

    def __init__(self, root, text, ticked, on_change, detail=None, side=None):
        self.on_change = on_change
        self.hover = False
        self.ticked = None
        self.enabled = True
        row = tk.Frame(root, bg=BG, cursor="hand2")
        if side:
            row.pack(side=side, pady=(3, 1))
        else:
            row.pack(fill="x", padx=PAD, pady=(3, 1))
        self.box = tk.Canvas(row, width=self.SIZE, height=self.SIZE, bg=BG, highlightthickness=0,
                             cursor="hand2")
        # a label's text starts 3px in from its edge, so the box does too and they line up
        self.box.pack(side="left", padx=(3, 0))
        self.label = tk.Label(row, text=text, bg=BG, font=BODY, cursor="hand2")
        self.label.pack(side="left", padx=(8, 0))
        widgets = [row, self.box, self.label]
        if detail:
            quiet = tk.Label(row, text=detail, fg=LABEL, bg=BG, font=SMALL, cursor="hand2")
            quiet.pack(side="left", padx=(8, 0), pady=(1, 0))
            widgets.append(quiet)
        for widget in widgets:
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", lambda _e: self._hovering(True))
            widget.bind("<Leave>", lambda _e: self._hovering(False))
        self.widgets = widgets
        self.set(ticked)

    def set(self, ticked):
        if bool(ticked) is not self.ticked:     # a HUD may call this ten times a second
            self.ticked = bool(ticked)
            self._draw()

    def enable(self, on):
        if bool(on) is not self.enabled:
            self.enabled = bool(on)
            for widget in self.widgets:
                widget.config(cursor="hand2" if on else "")
            self._draw()

    def _click(self, _e):
        if not self.enabled:
            return
        self.set(not self.ticked)
        self.on_change(self.ticked)

    def _hovering(self, over):
        self.hover = over
        self._draw()

    def _draw(self):
        _draw_box(self.box, self.label, self.ticked, self.hover and self.enabled,
                  dim=not self.enabled)


class Choice:
    """A box per option, with exactly one of them ticked; click another to pick it. For
    either/or settings, where separate checkboxes could both end up ticked.

    `options` is [(value, word), ...], laid out `columns` to a row in columns of equal width,
    so choices stacked one above another line up, with `gap` pixels between columns.
    `on_change(value)` is called after a click; set() changes it without calling that,
    relabel({value: word}) changes the words, and enable(False) greys it out for a setting
    that doesn't apply just now. `frame` holds them, not yet placed - pack it with fill="x"
    for the columns to spread."""

    def __init__(self, parent, options, value, on_change, columns=2, gap=0):
        self.on_change = on_change
        self.hover = None
        self.enabled = True
        self.value = object()                   # nothing yet, so the first set() draws
        self.frame = tk.Frame(parent, bg=BG)
        self.parts = {}
        for n, (option, word) in enumerate(options):
            cell = tk.Frame(self.frame, bg=BG, cursor="hand2")
            cell.grid(row=n // columns, column=n % columns, sticky="w", pady=(3, 1),
                      padx=(gap if n % columns else 0, 0))
            box = tk.Canvas(cell, width=Checkbox.SIZE, height=Checkbox.SIZE, bg=BG,
                            highlightthickness=0, cursor="hand2")
            box.pack(side="left", padx=(3, 0))  # in line with text above, as in Checkbox
            label = tk.Label(cell, text=word, bg=BG, font=BODY, cursor="hand2")
            label.pack(side="left", padx=(8, 0))
            for widget in (cell, box, label):
                widget.bind("<Button-1>", lambda _e, o=option: self._click(o))
                widget.bind("<Enter>", lambda _e, o=option: self._hovering(o))
                widget.bind("<Leave>", lambda _e: self._hovering(None))
            self.parts[option] = (cell, box, label)
        for column in range(columns):
            self.frame.grid_columnconfigure(column, weight=1, uniform="choice")
        self.set(value)

    def set(self, value):
        if value != self.value:                 # a HUD may call this ten times a second
            self.value = value
            self._draw()

    def relabel(self, words):
        for option, word in words.items():
            self.parts[option][2].config(text=word)

    def enable(self, on):
        """Off, it's grey all over: what's picked still shows, and clicks do nothing."""
        if bool(on) is not self.enabled:
            self.enabled = bool(on)
            for widgets in self.parts.values():
                for widget in widgets:
                    widget.config(cursor="hand2" if on else "")
            self._draw()

    def _click(self, option):
        if self.enabled and option != self.value:
            self.set(option)
            self.on_change(option)

    def _hovering(self, option):
        self.hover = option
        self._draw()

    def _draw(self):
        for option, (_cell, box, label) in self.parts.items():
            _draw_box(box, label, option == self.value, option == self.hover and self.enabled,
                      dim=not self.enabled)


class Lamp:
    """A feature's name with a small square that fills in while it's on - the settings window's
    tick box, shrunk to sit in a bar.

    Three looks: lit, in colour, while the feature is working; `ready`, filled in but grey,
    when it's set on and nothing is live yet; and an empty grey outline when it's off.
    set(lit, word, ready) changes it, and the word too if one is given. With `on_click` it's
    also the switch: it takes a hand cursor and brightens under the mouse. `frame` holds it,
    not yet placed."""

    SIZE = 9

    def __init__(self, parent, word, font=VALUE, on_click=None):
        self.frame = tk.Frame(parent, bg=BG)
        self.box = tk.Canvas(self.frame, width=self.SIZE, height=self.SIZE, bg=BG,
                             highlightthickness=0)
        self.box.pack(side="left")
        self.label = tk.Label(self.frame, text=word, bg=BG, font=font)
        self.label.pack(side="left", padx=(5, 0))
        self.word, self.lit, self.ready, self.hover = word, False, False, False
        if on_click:
            for widget in (self.frame, self.box, self.label):
                widget.config(cursor="hand2")
                widget.bind("<Button-1>", lambda _e: on_click())
                widget.bind("<Enter>", lambda _e: self._hovering(True))
                widget.bind("<Leave>", lambda _e: self._hovering(False))
        self._shown = None
        self._draw()

    def set(self, lit, word=None, ready=False):
        if word is not None and word != self.word:
            self.word = word
            self.label.config(text=word)
        self.lit, self.ready = bool(lit), bool(ready)
        self._draw()

    def _hovering(self, over):
        self.hover = over
        self._draw()

    def _draw(self):
        look = (self.lit, self.ready and not self.lit, self.hover)
        if look == self._shown:                 # the HUD calls set() ten times a second
            return
        self._shown = look
        colour = CYAN if self.lit else quiet(self.hover)
        self.box.delete("all")
        self.box.create_rectangle(0, 0, self.SIZE - 1, self.SIZE - 1, outline=colour)
        if self.lit or self.ready:
            self.box.create_rectangle(2, 2, self.SIZE - 3, self.SIZE - 3, fill=colour, outline="")
        self.label.config(fg=TEXT if self.lit else quiet(self.hover))


class Action:
    """A word on a bar that does something when clicked - a Lamp's lettering without its
    square, since it isn't a switch. `colour` is what it lights up in.

    set(look) picks one of four: "off" - grey, as a lamp is while nothing is live, a little
    brighter under the mouse; "ready" - bright, lighting up in its colour under the mouse;
    "running" - lit in its colour, for what's under way (clicking it stops it); "dead" -
    faint, and clicking does nothing. `label` is the widget, not yet placed."""

    def __init__(self, parent, word, colour=CYAN, font=VALUE, on_click=None):
        self.label = tk.Label(parent, text=word, bg=BG, font=font)
        self.colour, self.on_click = colour, on_click
        self.look, self.hover, self._shown = "off", False, None
        self.label.bind("<Button-1>", lambda _e: self._click())
        self.label.bind("<Enter>", lambda _e: self._hovering(True))
        self.label.bind("<Leave>", lambda _e: self._hovering(False))
        self._draw()

    def set(self, look):
        self.look = look
        self._draw()

    def _click(self):
        if self.look != "dead" and self.on_click:
            self.on_click()

    def _hovering(self, over):
        self.hover = over
        self._draw()

    def _draw(self):
        state = (self.look, self.hover)
        if state == self._shown:                # the HUD calls set() ten times a second
            return
        self._shown = state
        if self.look == "running":
            fg = self.colour
        elif self.look == "dead":
            fg = FAINT
        elif self.look == "ready":
            fg = self.colour if self.hover else TEXT
        else:
            fg = quiet(self.hover)
        self.label.config(fg=fg, cursor="" if self.look == "dead" else "hand2")


def _draw_box(box, label, ticked, hover, dim=False):
    """A checkbox or choice box: an outline, filled in when ticked, the text lit to match.
    `dim` is for a setting that doesn't apply just now: grey all over, the tick still showing."""
    size = Checkbox.SIZE
    if dim:
        edge, fill, text = FAINT, LABEL, LABEL
    else:
        edge = CYAN if ticked else (TEXT if hover else LABEL)
        fill, text = CYAN, TEXT if ticked or hover else KEY
    box.delete("all")
    box.create_rectangle(0, 0, size - 1, size - 1, outline=edge)
    if ticked:
        box.create_rectangle(3, 3, size - 4, size - 4, fill=fill, outline="")
    label.config(fg=text)


def entry(parent, width):
    """A text box: bright text on a dark field, edged in cyan while you type in it."""
    box = tk.Entry(parent, width=width, bg=LINE, fg=TEXT, insertbackground=TEXT, font=VALUE,
                   relief="flat", bd=2, highlightthickness=1, highlightbackground=LINE,
                   highlightcolor=CYAN, selectbackground=LABEL, selectforeground=TEXT)
    # A borderless window only takes typing once it's been made the active one.
    box.bind("<Button-1>", lambda _e: box.focus_force(), add="+")
    return box


def heading(root, text):
    """A small dim title over a group of settings."""
    tk.Label(root, text=text, fg=LABEL, bg=BG, font=SMALL_BOLD, anchor="w").pack(
        fill="x", padx=PAD, pady=(2, 0))


def note(root, text, lines=None):
    """A small, quiet line of help under a setting. Give `lines` if the text will change, so
    the space it takes doesn't. Returns the label."""
    label = tk.Label(root, text=text, fg=KEY_ACTION, bg=BG, font=SMALL, anchor="nw",
                     justify="left", wraplength=WIDTH - 2 * PAD)
    if lines:
        label.config(height=lines)
    label.pack(fill="x", padx=PAD, pady=(1, 0))
    return label


def status_row(root):
    """The big mode word on the left, MEM OK / NO MEM on the right. Returns both labels."""
    row = tk.Frame(root, bg=BG)
    row.pack(fill="x", padx=PAD, pady=(0, 2))
    status = tk.Label(row, text="OFF", fg=FAINT, bg=BG, font=STATUS, anchor="w")
    status.pack(side="left")
    mem = tk.Label(row, text="", bg=BG, font=SMALL_BOLD, anchor="e")
    mem.pack(side="right", pady=(4, 0))
    return status, mem


def show_mem(label, ok):
    label.config(text="MEM OK" if ok else "NO MEM", fg=GOOD if ok else BAD)


class Progress:
    """A 2-pixel bar; set(None) hides the fill."""

    def __init__(self, root):
        self.track = tk.Frame(root, bg=BG, height=2)
        self.track.pack(fill="x", padx=PAD, pady=(0, 4))
        self.fill = tk.Frame(self.track, bg=CYAN, height=2)

    def set(self, fraction, colour=CYAN):
        if fraction is None:
            self.fill.place_forget()
        else:
            self.fill.config(bg=colour)
            self.fill.place(x=0, y=0, relheight=1, relwidth=max(0.0, min(1.0, fraction)))


def divider(root, above=3, below=3, hidden=False):
    """A line across. `hidden` keeps its space without drawing it."""
    tk.Frame(root, bg=BG if hidden else LINE, height=1).pack(fill="x", padx=PAD - 2,
                                                            pady=(above, below))


def pair_row(root, left, right):
    """Two LABEL value pairs, one each side. Returns the two value labels."""
    row = tk.Frame(root, bg=BG)
    row.pack(fill="x", padx=PAD, pady=(1, 0))
    values = []
    for text, side in ((left, "left"), (right, "right")):
        cell = tk.Frame(row, bg=BG)
        cell.pack(side=side)
        tk.Label(cell, text=text, fg=LABEL, bg=BG, font=BODY).pack(side="left")
        value = tk.Label(cell, text="", fg=TEXT, bg=BG, font=VALUE)
        value.pack(side="left", padx=(6, 0))
        values.append(value)
    return values


def bottom_space(root):
    """Closes a HUD that ends on a label/value row with the same 12px under the text as key_legend."""
    tk.Frame(root, bg=BG, height=6).pack(fill="x")


def message(root, lines=4):
    """A fixed-height, word-wrapped line for what just happened, so the window never jumps."""
    return tk.Label(root, text="", fg=CYAN, bg=BG, font=SMALL, anchor="nw", justify="left",
                    wraplength=WIDTH - 2 * PAD, height=lines)


def key_legend(root, keys):
    """[(key, what it does), ...] in two columns, key names brighter than the actions."""
    grid = tk.Frame(root, bg=BG)
    grid.pack(fill="x", padx=PAD, pady=(0, 7))
    half = (len(keys) + 1) // 2
    for n, (key, action) in enumerate(keys):
        cell = tk.Frame(grid, bg=BG)
        cell.grid(row=n % half, column=n // half, sticky="w", padx=(0, 18), pady=(0, 1))
        tk.Label(cell, text=key.ljust(3), fg=KEY, bg=BG, font=SMALL_BOLD).pack(side="left")
        tk.Label(cell, text=action, fg=KEY_ACTION, bg=BG, font=SMALL).pack(side="left")
    return grid


# ---- hiding the bar while you play ----

def show_bar(root, on):
    """A bar hidden, or shown again on top of everything - without taking the game's place in
    front, which would drop a game in exclusive fullscreen to the desktop (Tk's own show does
    take it). True if Windows did it."""
    import ctypes
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, w.UINT]
    # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE, and SWP_SHOWWINDOW or SWP_HIDEWINDOW
    flags = 0x0001 | 0x0002 | 0x0010 | (0x0040 if on else 0x0080)
    return bool(user32.SetWindowPos(int(root.wm_frame(), 16), -1, 0, 0, 0, 0, flags))  # HWND_TOPMOST


def raise_bar(root):
    """The bar back on top of everything, as it is - shown or hidden - without taking the
    game's place in front."""
    import ctypes
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, w.UINT]
    # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE, before HWND_TOPMOST
    return bool(user32.SetWindowPos(int(root.wm_frame(), 16), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010))


def game_in_front(game_pid):
    """The game is the window in front."""
    import ctypes
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = w.HWND
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    front = user32.GetForegroundWindow()
    owner = w.DWORD()
    if not front or not user32.GetWindowThreadProcessId(front, ctypes.byref(owner)):
        return False
    return owner.value == game_pid


def pointer_showing():
    """A mouse pointer is on screen - in the game, its menu, console or times panel is open."""
    import ctypes
    from ctypes import wintypes as w

    class CursorInfo(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD), ("hCursor", w.HANDLE),
                    ("ptScreenPos", w.POINT)]

    info = CursorInfo(cbSize=ctypes.sizeof(CursorInfo))
    if not ctypes.WinDLL("user32").GetCursorInfo(ctypes.byref(info)):
        return True
    return bool(info.flags & 1)                     # CURSOR_SHOWING


def playing(game_pid):
    """You're playing: the game is the window in front and shows no mouse pointer."""
    return game_in_front(game_pid) and not pointer_showing()


class AutoHide:
    """HIDE WHILE PLAYING: the bar steps away while you play, and comes back the moment the game
    shows a mouse pointer (Esc, the console, the times panel - how you click the bar anyway),
    you switch to another window, or something needs your eye. On some PCs anything over the
    game makes Windows compose the screen, about a frame more for every frame to reach it (the
    desktop: 0.6 -> 7.9 ms). Back at once; away only after SETTLE seconds of play, so a pointer
    flickering doesn't flash it.

    An option, off until ticked: off, the bar is never hidden - only lifted back over the game
    (see update)."""

    SETTLE = 0.3
    RAISE_EVERY = 1.0

    def __init__(self, root, in_front=game_in_front, pointer=pointer_showing, show=show_bar,
                 lift=raise_bar, clock=None):
        import time
        self.root, self._in_front, self._pointer = root, in_front, pointer
        self._show, self._lift = show, lift
        self._clock = clock or time.monotonic
        self.hidden = False
        self._want, self._since, self._raised = False, 0.0, None

    def update(self, on, game_pid, keep=False):
        """From the bar's loop, ten times a second: `on` the setting, `game_pid` the game's
        process (None when there's none), `keep` true while the bar must stay - a window of
        the tool's open, or a problem to see. Whether the bar is hidden now.

        Shown, with the game in front, the bar is lifted back on top once a second: in
        Fullscreen the game's window is topmost too, and clicking into it put it over the
        bars - out of sight on the desktop, whatever this option said."""
        front = bool(game_pid) and self._in_front(game_pid)
        want = bool(on and front and not keep and not self._pointer())
        now = self._clock()
        if want != self._want:
            self._want, self._since = want, now
        if want and not self.hidden and now - self._since >= self.SETTLE:
            self._show(self.root, False)
            self.hidden = True
        elif not want and self.hidden:
            self._show(self.root, True)
            self.hidden, self._raised = False, now
        elif not self.hidden and front and (self._raised is None or now - self._raised >= self.RAISE_EVERY):
            self._lift(self.root)
            self._raised = now
        return self.hidden

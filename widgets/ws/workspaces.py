import gi
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, GObject, Gdk, Pango, PangoCairo
import cairo

__all__ = ["Workspaces"]

class WSProvider(GObject.Object):
	@GObject.Signal(arg_types=[object])
	def color(self, rgb): pass
	@GObject.Signal(arg_types=[object])
	def workspaces(self, workspaces): pass

	def set_workspace(self, name): pass

class Workspaces(Gtk.Box):
	def __init__(self, provider):
		super().__init__(spacing=1)
		self.provider = provider
		self.provider.connect("color", self.update_color)
		self.provider.connect("workspaces", self.update_workspaces)
		self.buttons = {}
		self.active_color = (0, 0, 0, 0)

	def update_color(self, provider, color):
		for button in self.buttons.values():
			button.set_color(color)
		self.active_color = color

	def update_workspaces(self, provider, workspaces):
		current = {a[0] for a in workspaces}
		for name in list(self.buttons):
			if name not in current:
				self.remove(self.buttons[name])
				del self.buttons[name]
		for i, (name, state) in enumerate(workspaces):
			if name not in self.buttons:
				self.buttons[name] = WorkspaceButton(name, self.active_color)
				self.buttons[name].connect("activate", lambda button, name: self.provider.set_workspace(name), name)
				self.pack_start(self.buttons[name], False, False, 0)
				self.buttons[name].show()
			self.buttons[name].set_state(state)
			self.reorder_child(self.buttons[name], i)

PADDING = 4

class WorkspaceButton(Gtk.DrawingArea):
	@GObject.Signal
	def activate(self): pass

	def __init__(self, name, color):
		super().__init__()
		self.name = name
		self.state = 0
		self.active_color = color

		pango = self.get_pango_context()
		layout = Pango.Layout.new(pango)
		layout.set_text(self.name, -1)
		ext = layout.get_pixel_extents()[1]
		self.set_size_request(2 + 2*PADDING + ext.width, 0)

		self.connect("draw", self.draw)
		self.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
		self.connect("button-press-event", self.on_mouse)

	def on_mouse(self, _, evt):
		if (evt.button, evt.type) == (1, Gdk.EventType.BUTTON_PRESS):
			self.emit("activate")

	def set_state(self, state):
		if state != self.state:
			self.state = state
			self.queue_draw()

	def set_color(self, color):
		self.active_color = tuple(color)
		if self.state == 2:
			self.queue_draw()

	def draw(self, _, ctx):
		ctx.set_antialias(cairo.ANTIALIAS_NONE)
		ctx.set_line_width(1)
		ctx.set_line_join(cairo.LINE_JOIN_BEVEL)
		ctx.set_line_cap(cairo.LINE_CAP_BUTT)

		style = self.get_style_context()
		r, g, b, a = style.get_color(style.get_state())

		w = self.get_allocated_width()
		h = self.get_allocated_height()

		bg, border, text = None, None, None

		if self.state == 0:
			border = (r, g, b, a/8)
			text = (r, g, b, a/2)
		if self.state == 1:
			border = (r, g, b, a/4)
			text = (r, g, b, a)
		if self.state == 2:
			bg = self.active_color
			ar,ag,ab,aa = self.active_color
			border = ((r+ar*5)/6, (g+ag*5)/6, (b+ab*5)/6, 1)
			text = (r, g, b, a)
		if self.state == 3:
			bg = (2/3, 0, 0, 1)
			border = (r, g, b, a/8)
			text = (r, g, b, a)

		if bg:
			ctx.set_source_rgba(*bg)
			ctx.move_to(1, 2)
			ctx.line_to(1, h-2)
			ctx.line_to(w-1, h-2)
			ctx.line_to(w-1, 2)
			ctx.close_path()
			ctx.fill()
		if border:
			ctx.set_source_rgba(*border)
			ctx.move_to(.5, 1.5)
			ctx.line_to(.5, h-1.5)
			ctx.line_to(w-.5, h-1.5)
			ctx.line_to(w-.5, 1.5)
			ctx.close_path()
			ctx.stroke()
		if text:
			ctx.set_source_rgba(*text)
			pango = self.get_pango_context()
			layout = Pango.Layout.new(pango)
			layout.set_text(self.name, -1)
			ext = layout.get_pixel_extents()[1]
			ctx.move_to((w-ext.width)/2, (h-ext.height)/2)
			PangoCairo.show_layout(ctx, layout)

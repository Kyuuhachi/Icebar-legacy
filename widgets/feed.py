from gi.repository import Gtk, GLib, Gio, GObject, Gdk
from pathlib import Path
import configparser
import feedparser
import bs4
import sqlite3
import util
import webbrowser

__all__ = ["Feeds", "RSSFeed", "FFNFeed"]

def getProfilePath():
	FF_PATH = Path("~/.mozilla/firefox").expanduser()

	ini = configparser.ConfigParser()
	ini.read(FF_PATH / "profiles.ini")

	for sec in ini:
		if "default" in ini[sec]:
			return str(FF_PATH / ini[sec]["path"])

def clean_url(url):
	from urllib.parse import urlparse, urlunparse
	parse = urlparse(url)
	return urlunparse(parse._replace(netloc=parse.netloc.lower()))

icon = Gtk.IconTheme.get_default().load_icon("application-rss+xml", 16, 0)
iconGray = icon.copy()
iconGray.saturate_and_pixelate(iconGray, 0, False)

class Feeds(Gtk.EventBox):
	def __init__(self, *feeds, spacing=3):
		super().__init__()

		self.sql = sqlite3.connect(getProfilePath() + "/places.sqlite")

		self.icon = Gtk.Label()
		self.text = Gtk.Label()
		box = Gtk.Box(spacing=spacing)
		box.pack_start(self.icon, False, False, 0)
		box.pack_start(self.text, False, False, 0)
		self.add(box)

		self.menu = Gtk.Menu()
		self.menu.set_take_focus(False)
		util.popupify(self.menu.get_parent(), self)
		self.feeds = []

		for feed in feeds:
			if feed is None:
				self.menu.add(Gtk.SeparatorMenuItem())
				continue
			feed.num = len(self.feeds)
			menu = Gtk.Menu()
			image = Gtk.Image()
			menuitem = Gtk.ImageMenuItem.new_with_label(feed.name)
			menuitem.set_always_show_image(True)
			menuitem.set_image(image)
			menuitem.set_submenu(menu)
			self.menu.add(menuitem)
			self.feeds.append((feed, image, menuitem, menu))

			feed.parent = self
			feed.connect("updated", self.feed_updated)
			feed.fetch()

		GLib.timeout_add_seconds(5, self.hist, [f for f,_,_,_ in self.feeds])

		self.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
		self.connect("button-press-event", self.click)

		GLib.idle_add(self.update, priority=200)

	def feed_updated(self, feed):
		_, image, menuitem, menu = self.feeds[feed.num]

		for child in menu.get_children():
			menu.remove(child)

		browserOpen = lambda item, url: webbrowser.open(url)
		image.set_from_pixbuf([icon, iconGray][not feed.has_unread()])

		menuitem = Gtk.MenuItem()
		menuitem.set_label(feed.title or feed.info.name)
		menuitem.connect("activate", browserOpen, feed.info.url)
		menu.add(menuitem)
		menu.add(Gtk.SeparatorMenuItem())

		for e in feed.info.entries:
			menuitem = Gtk.ImageMenuItem()
			menuitem.set_label(feed.titlefmt(e.name))
			menuitem.set_always_show_image(True)
			menuitem.set_image(Gtk.Image.new_from_pixbuf([icon, iconGray][e.visited]))
			menuitem.connect("activate", browserOpen, e.url)
			menu.add(menuitem)

		self.menu.show_all()

		self.update()

	def update(self):
		num = sum(f.has_unread() for f,_,_,_ in self.feeds)
		self.icon.set_text(["", ""][bool(num)])
		self.text.set_text(str(num))
		self.text.set_visible(bool(num))

	def hist(self, feeds):
		urls = []
		for feed in feeds:
			urls += (e.url for e in feed.info.entries)
		query = "SELECT url FROM moz_places WHERE url IN ({})".format(",".join(["?"] * len(urls)))
		visited = {n[0] for n in self.sql.execute(query, urls)}
		for feed in feeds:
			feed.check_hist(visited)
		return True

	def click(self, _, evt):
		if (evt.button, evt.type) == (1, Gdk.EventType.BUTTON_PRESS):
			self.menu.popup_at_widget(self, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH)

class FeedInfo:
	def __init__(self, name, url, entries):
		self.name = name
		self.url = clean_url(url)
		self.entries = entries[:15]
class FeedEntry:
	def __init__(self, name, url):
		self.name = name
		self.url = clean_url(url)
		self.visited = False

class _Feed(GObject.Object):
	def __init__(self, name, url, titlefmt=lambda l: l, title=None):
		super().__init__()
		self.name = name
		self.url = url
		self.file = Gio.File.new_for_uri(self.url)
		self.titlefmt = titlefmt
		self.title = title

		self.info = FeedInfo(f"<{name}>", "", [])
		self.sql = None # Filled out by Feeds

		GLib.timeout_add_seconds(3600, self.fetch)

	@GObject.Signal
	def updated(self): pass

	def fetch(self):
		def _on_finish(source, res):
			status, data, etag = source.load_contents_finish(res)
			assert status is True
			self.info = self.load_feed(data)
			self.parent.hist([self])
		self.file.load_contents_async(None, _on_finish)
		return True

	def check_hist(self, visited):
		for entry in self.info.entries:
			entry.visited = entry.url in visited
		self.emit("updated")

	def load_feed(self, data):
		raise NotImplementedError()

	def has_unread(self):
		return bool(self.info.entries) and not self.info.entries[0].visited

	def __repr__(self):
		return f"{type(self).__name__}({self.name!r}, {self.url!r})"

class RSSFeed(_Feed):
	def __init__(self, name, url, match=lambda e: True, **kwargs):
		super().__init__(name=name, url=url, **kwargs)
		self._match = match

	def load_feed(self, data):
		entries = []
		feed = feedparser.parse(data) # TODO I think this is slow.
		for e in feed.entries:
			if hasattr(e, "feedburner_origlink"):
				e.link = e.feedburner_origlink
			if self._match(e):
				entries.append(FeedEntry(e.title, e.link))
		return FeedInfo(feed.feed.title, feed.feed.link, entries)

class FFNFeed(_Feed):
	def __init__(self, name, id, **kwargs):
		super().__init__(name=name, url="https://www.fanfiction.net/s/{}".format(id), **kwargs)

	def load_feed(self, data):
		soup = bs4.BeautifulSoup(data, features="lxml")

		title = soup.find(id="profile_top").find("b").text
		chap_select = soup.find(id="chap_select")
		urlname = chap_select["onchange"].split()[-1][2:-2]

		return FeedInfo(title, self.url, [
			FeedEntry(
				opt.text,
				"{}/{}/{}".format(self.url, opt.get("value"), urlname)
			) for opt in chap_select.find_all("option")[::-1]
		])

"""Splitter that collapses on click and resizes when the strip is dragged."""

from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.splitter import Splitter

# Ignore jitter below this so a click is not treated as a tiny resize.
_DRAG_THRESHOLD = dp(8)
_MIN_SIBLING_SIZE = dp(120)


class CollapsibleSplitter(Splitter):
    """Vertical splitter whose strip toggles collapse unless the pointer is dragged.

    A press that stays within the drag threshold collapses or restores the pane.
    Moving past the threshold resizes it like a normal splitter.
    """

    collapsed = BooleanProperty(False)
    _restore_height = NumericProperty(0)
    _did_drag = BooleanProperty(False)
    _press_pos = (0.0, 0.0)

    def strip_down(self, instance, touch):
        if not instance.collide_point(*touch.pos):
            return False
        # Do not grab or return True: SplitterStrip is a Button, and skipping
        # ButtonBehavior.on_touch_down leaves touch.ud unset, so on_touch_up
        # asserts. The Button grabs the strip after this observer runs.
        self._press_pos = (touch.x, touch.y)
        self._did_drag = False
        self.dispatch("on_press")

    def strip_move(self, instance, touch):
        if not self._is_our_grab(touch, instance):
            return False
        if not self._did_drag:
            if not self._moved_enough(touch):
                return False
            self._did_drag = True
            if self.collapsed:
                self.collapsed = False
                self.size_hint_y = None
        self._resize_from_touch(touch)
        return True

    def strip_up(self, instance, touch):
        if not self._is_our_grab(touch, instance):
            return
        if not self._did_drag:
            self.toggle_collapsed()
        elif self.height <= self.strip_size + 1:
            self.collapsed = True
            self._restore_height = self._restore_height or self.height
        else:
            self.collapsed = False
            self._restore_height = self.height
        self.dispatch("on_release")

    def toggle_collapsed(self):
        if self.collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self):
        if not self.collapsed:
            self._restore_height = max(self.height, self.strip_size)
        self.collapsed = True
        self.size_hint_y = None
        self.height = self.strip_size

    def expand(self):
        self.collapsed = False
        self.size_hint_y = None
        restore = self._restore_height
        if restore <= self.strip_size:
            restore = 0.3 * (self.parent.height if self.parent else self.height or 200)
        self.height = max(self.min_size, min(restore, self.max_size))

    def _do_size(self, instance, value):
        if self.collapsed:
            return
        super()._do_size(instance, value)

    def rescale_parent_proportion(self, *args):
        if self.parent is not None:
            self.max_size = max(self.min_size, self.parent.height - _MIN_SIBLING_SIZE)
        if self.collapsed:
            self.height = self.strip_size
            return
        super().rescale_parent_proportion(*args)

    def _moved_enough(self, touch):
        dx = touch.x - self._press_pos[0]
        dy = touch.y - self._press_pos[1]
        return (dx * dx + dy * dy) >= _DRAG_THRESHOLD * _DRAG_THRESHOLD

    def _resize_from_touch(self, touch):
        diff_y = touch.dy
        if self.sizable_from[0] == "b":
            diff_y *= -1
        if self.size_hint_y:
            self.size_hint_y = None
        max_height = self.max_size
        if self.keep_within_parent and self.parent is not None:
            max_height = min(max_height, self.parent.top - self.y)
        self.height = max(self.min_size, min(self.height + diff_y, max_height))
        if self.parent is not None and self.parent.height:
            self._parent_proportion = self.height / self.parent.height

    @staticmethod
    def _is_our_grab(touch, instance):
        return touch.grab_current is instance


if "CollapsibleSplitter" not in Factory.classes:
    Factory.register("CollapsibleSplitter", cls=CollapsibleSplitter)

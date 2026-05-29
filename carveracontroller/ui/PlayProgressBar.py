from kivy.core.text import Label as CoreLabel
from kivy.factory import Factory
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.CNC import LASER_TOOL_NUMBER, ZPROBE_TOOL_NUMBER, PROBE_3D_TOOL_NUMBER
from carveracontroller.GcodeViewer import tool_marker_palette_rgb

DEFAULT_MARKER_LABEL_BG_COLOR = (210 / 255, 210 / 255, 210 / 255, 1)
MARKER_LABEL_TEXT_COLOR = (30 / 255, 30 / 255, 30 / 255, 1)

def play_percent_from_line(line_no, line_count):
    if line_count <= 0 or line_no <= 0:
        return 0.0
    return min(100.0, line_no / float(line_count) * 100.0)


def tool_change_markers_to_percents(markers, line_count):
    if line_count <= 0:
        return []
    percents = []
    for line_no, label in markers:
        percents.append((play_percent_from_line(line_no, line_count), label))
    return percents


def _marker_label_bg_color(label):
    """Return an rgba background color for a tool marker label (matches toolpath/legend palette)."""
    if label == 'L':
        tool_num = LASER_TOOL_NUMBER
    elif label == 'P':
        tool_num = ZPROBE_TOOL_NUMBER
    elif label == '3DP':
        tool_num = PROBE_3D_TOOL_NUMBER
    elif label.startswith('T') and label[1:].isdigit():
        tool_num = int(label[1:])
    else:
        return DEFAULT_MARKER_LABEL_BG_COLOR
    rgb = tool_marker_palette_rgb(tool_num)
    return (rgb[0], rgb[1], rgb[2], 1.0)


def _marker_label_intervals_overlap(left, width, intervals, gap):
    right = left + width
    for interval_left, interval_right in intervals:
        if left < interval_right + gap and right > interval_left - gap:
            return True
    return False


def _layout_tool_marker_labels(items, track_w, gap=None):
    """Assign non-overlapping label positions on a single row."""
    if not items:
        return items
    if gap is None:
        gap = dp(1)

    def clamp_left(left, width):
        return max(0, min(track_w - width, left))

    row_intervals = [[]]
    for item in sorted(items, key=lambda entry: entry['local_x']):
        width = item['label_w']
        ideal_left = item['ideal_left']
        left = clamp_left(ideal_left, width)
        if _marker_label_intervals_overlap(left, width, row_intervals[0], gap):
            left = ideal_left
            for interval_left, interval_right in sorted(row_intervals[0]):
                if left < interval_right + gap and left + width > interval_left - gap:
                    left = interval_right + gap
            left = clamp_left(left, width)
        if not _marker_label_intervals_overlap(left, width, row_intervals[0], gap):
            item['left'] = left
            item['row'] = 0
            item['show_label'] = True
            row_intervals[0].append((left, left + width))
        else:
            item['show_label'] = False
            item['left'] = clamp_left(ideal_left, width)
            item['row'] = 0

    row_items = [item for item in items if item.get('show_label')]
    row_items.sort(key=lambda entry: entry['left'])
    for _ in range(len(row_items) + 1):
        for index in range(1, len(row_items)):
            previous = row_items[index - 1]
            current = row_items[index]
            min_left = previous['left'] + previous['label_w'] + gap
            if current['left'] < min_left:
                current['left'] = min_left
        for index in range(len(row_items) - 2, -1, -1):
            current = row_items[index]
            nxt = row_items[index + 1]
            max_left = nxt['left'] - gap - current['label_w']
            if current['left'] > max_left:
                current['left'] = max_left
        if row_items:
            first = row_items[0]
            first['left'] = clamp_left(first['left'], first['label_w'])
            last = row_items[-1]
            last['left'] = clamp_left(last['left'], last['label_w'])

    row_items = [item for item in items if item.get('show_label')]
    row_items.sort(key=lambda entry: entry['left'])
    for index in range(1, len(row_items)):
        previous = row_items[index - 1]
        current = row_items[index]
        if current['left'] < previous['left'] + previous['label_w'] + gap - 0.5:
            current['show_label'] = False

    return items


class PlayProgressBar(BoxLayout):
    value = NumericProperty(0)
    color = ListProperty([52 / 255, 166 / 255, 208 / 255, 1])
    tool_markers = ListProperty([])

    LABEL_ROW_H = dp(12)

    def __init__(self, **kwargs):
        super(PlayProgressBar, self).__init__(**kwargs)
        with self.canvas.before:
            Color(50 / 255, 50 / 255, 50 / 255, 1)
            self._bg_rect = Rectangle(pos=self.pos, size=(0, 0))
            self._fill_color = Color(*self.color)
            self._fill_rect = Rectangle(pos=self.pos, size=(0, 0))
        self.bind(
            pos=self._update_canvas,
            size=self._update_canvas,
            value=self._update_canvas,
            color=self._update_fill_color,
            tool_markers=self._update_markers,
        )

    def _track_width(self):
        return max(0, self.width - dp(5)) if self.width > 0 else 0

    def _fill_offset(self):
        return dp(5)

    def _position_for_percent(self, track_w, percent):
        return track_w * percent / 100.0 + self._fill_offset()

    def _update_fill_color(self, instance, value):
        self._fill_color.rgba = value

    def _update_canvas(self, *args):
        track_w = self._track_width()
        bar_h = self.height if self.width > 0 else 0
        self._bg_rect.pos = self.pos
        self._bg_rect.size = (track_w, bar_h)
        fill_w = self._position_for_percent(track_w, self.value) if self.width > 0 else 0
        self._fill_rect.pos = self.pos
        self._fill_rect.size = (fill_w, bar_h)
        self._update_markers(None, self.tool_markers)

    def _prepare_marker_draw_items(self, value, track_w):
        layout_w = track_w + self._fill_offset()
        items = []
        for percent, label in value:
            local_x = self._position_for_percent(track_w, percent)
            label_bg_color = _marker_label_bg_color(label)
            core = CoreLabel(
                text=label,
                font_size=dp(9),
                color=MARKER_LABEL_TEXT_COLOR,
                font_name='ARIALUNI',
            )
            core.refresh()
            label_w, label_h = core.texture.size
            items.append({
                'percent': percent,
                'label': label,
                'local_x': local_x,
                'label_w': label_w,
                'label_h': label_h,
                'label_bg_color': label_bg_color,
                'core': core,
                'ideal_left': local_x - label_w / 2.0,
                'left': local_x - label_w / 2.0,
                'row': 0,
                'show_label': True,
            })
        return _layout_tool_marker_labels(items, layout_w)

    def _label_y_for_row(self, oy, row, label_h):
        row_top = oy + self.height - dp(1) - (row + 1) * self.LABEL_ROW_H
        return row_top + (self.LABEL_ROW_H - label_h) / 2.0

    def _update_markers(self, instance, value):
        self.canvas.after.clear()
        track_w = self._track_width()
        bar_h = self.height if self.width > 0 else 0
        if track_w <= 0 or bar_h <= 0 or not value:
            return
        label_pad = dp(2)
        ox, oy = self.pos
        draw_items = self._prepare_marker_draw_items(value, track_w)
        with self.canvas.after:
            for item in draw_items:
                x = ox + item['local_x']
                Color(200 / 255, 200 / 255, 200 / 255, 0.6)
                Line(points=[x, oy, x, oy + bar_h], width=1)
            for item in draw_items:
                if not item.get('show_label', True):
                    continue
                label_w = item['label_w']
                label_h = item['label_h']
                label_x = ox + item['left']
                label_y = self._label_y_for_row(oy, item['row'], label_h)
                Color(*item['label_bg_color'])
                Rectangle(
                    pos=(label_x - label_pad, label_y - label_pad / 2.0),
                    size=(label_w + label_pad * 2, label_h + label_pad),
                )
                Color(1, 1, 1, 1)
                Rectangle(
                    texture=item['core'].texture,
                    pos=(label_x, label_y),
                    size=(label_w, label_h),
                )


Factory.register('PlayProgressBar', cls=PlayProgressBar)

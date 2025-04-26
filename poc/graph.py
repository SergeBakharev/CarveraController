import itertools
import SoloPy as solo
from kivy.utils import get_color_from_hex as rgb
from kivy.uix.boxlayout import BoxLayout
from kivy.app import App
from kivy.clock import Clock
from kivy_garden.graph import Graph, SmoothLinePlot


class TestApp(App):

    def build(self):
        b = BoxLayout(orientation='vertical')
        # example of a custom theme
        colors = itertools.cycle([
            rgb('7dac9f'), rgb('dc7062'), rgb('66a8d4'), rgb('e5b060')])
        graph_theme = {
            'label_options': {
                'color': rgb('444444'),  # color of tick labels and titles
                'bold': True},
            'background_color': rgb('f8f8f2'),  # canvas background color
            'tick_color': rgb('808080'),  # ticks and grid
            'border_color': rgb('808080')}  # border drawn around each graph

        graph = Graph(
            xlabel='',
            ylabel='Amps / RPM (/2k)',
            x_ticks_minor=5,
            x_ticks_major=25,
            y_ticks_major=1,
            y_grid_label=True,
            x_grid_label=False,
            padding=5,
            xlog=False,
            ylog=False,
            x_grid=True,
            y_grid=True,
            xmin=0,
            xmax=30,
            ymin=0,
            ymax=10,
            **graph_theme)

        self.power_plot = SmoothLinePlot(color=next(colors))
        self.power_plot.points = [(x, 0) for x in range(30)]
        graph.add_plot(self.power_plot)

        self.speed_plot = SmoothLinePlot(color=next(colors))
        self.speed_plot.points = [(x, 0) for x in range(30)]
        graph.add_plot(self.speed_plot)

        self.solo = solo.SoloMotorControllerUart("COM6", 0, solo.UartBaudRate.RATE_937500)

        Clock.schedule_interval(self.update_points, 0.2)

        b.add_widget(graph)

        return b

    def update_points(self, *args):
        power, error = self.solo.get_quadrature_current_iq_feedback()
        speed, error = self.solo.get_speed_feedback()

        self.power_plot.points = self.shift_points(self.power_plot.points, power)
        self.speed_plot.points = self.shift_points(self.speed_plot.points, speed/2000)

    def shift_points(self, points, new_last_y):
        y_values = [y for _, y in points]

        for i in range(1, len(y_values)-1):
            points[i] = (points[i][0], y_values[i + 1])
        
        points = points[:-1]
        points.append((len(y_values),new_last_y))
        
        return points



TestApp().run()
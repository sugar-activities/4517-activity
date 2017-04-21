# -*- coding: utf-8 -*-
#Copyright (c) 2011-12 Walter Bender
#Copyright (c) 2012 Ignacio Rodríguez
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


from gi.repository import Gtk, GdkPixbuf, GObject, Gdk
import cairo

from random import uniform

from gettext import gettext as _

import logging
_logger = logging.getLogger('reflection-activity')

try:
    from sugar3.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

from sprites import Sprites, Sprite


# Grid dimensions must be even
TEN = 10
SIX = 6
DOT_SIZE = 40


class Game():

    def __init__(self, canvas, parent=None, colors=['#A0FFA0', '#FF8080']):
        self._activity = parent
        self._colors = [colors[0]]
        self._colors.append(colors[1])
        self._colors.append('#FFFFFF')
        self._colors.append('#000000')
        self._colors.append('#FF0000')
        self._colors.append('#FF8000')
        self._colors.append('#FFFF00')
        self._colors.append('#00FF00')
        self._colors.append('#00FFFF')
        self._colors.append('#0000FF')
        self._colors.append('#FF00FF')

        self._canvas = canvas
        if parent is not None:
            parent.show_all()
            self._parent = parent

        self._canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self._canvas.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self._canvas.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        self._canvas.connect("draw", self.__draw_cb)
        self._canvas.connect("button-press-event", self._button_press_cb)
        self._canvas.connect("button-release-event", self._button_release_cb)
        self._canvas.connect("motion-notify-event", self._mouse_move_cb)
        self._width = Gdk.Screen.width()
        self._height = Gdk.Screen.height() - (GRID_CELL_SIZE * 1.5)
        self._scale = self._width / (10 * DOT_SIZE * 1.2)
        self._dot_size = int(DOT_SIZE * self._scale)
        self._space = int(self._dot_size / 5.)
        self._orientation = 'horizontal'
        self.we_are_sharing = False
        self.playing_with_robot = False
        self._press = False
        self.last_spr = None
        self._timer = None
        self.roygbiv = False

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)
        self._dots = []
        for y in range(SIX):
            for x in range(TEN):
                xoffset = int((self._width - TEN * self._dot_size - \
                                   (TEN - 1) * self._space) / 2.)
                self._dots.append(
                    Sprite(self._sprites,
                           xoffset + x * (self._dot_size + self._space),
                           y * (self._dot_size + self._space),
                           self._new_dot(self._colors[2])))
                self._dots[-1].type = 2  # not set
                self._dots[-1].set_label_attributes(40)

        self.vline = Sprite(self._sprites,
                            int(self._width / 2.) - 1,
                            0, self._line(vertical=True))
        n = SIX / 2.
        self.hline = Sprite(
            self._sprites, 0,
            int(self._dot_size * n + self._space * (n - 0.5)) - 1,
            self._line(vertical=False))
        self.hline.hide()

        # and initialize a few variables we'll need.
        self._all_clear()

    def _all_clear(self):
        ''' Things to reinitialize when starting up a new game. '''
        for dot in self._dots:
            dot.type = 2
            dot.set_shape(self._new_dot(self._colors[2]))
            dot.set_label('')

        self._set_orientation()

    def _set_orientation(self):
        ''' Set bar and message for current orientation '''
        if self._orientation == 'horizontal':
            self.hline.hide()
            self.vline.set_layer(1000)
        elif self._orientation == 'vertical':
            self.hline.set_layer(1000)
            self.vline.hide()
        else:
            self.hline.set_layer(1000)
            self.vline.set_layer(1000)

        '''
        if self._orientation == 'horizontal':
            self._set_label(
                _('Click on the dots to make a horizontal reflection.'))
        elif self._orientation == 'vertical':
            self._set_label(
                _('Click on the dots to make a vertical reflection.'))
        else:
            self._set_label(
                _('Click on the dots to make a bilateral reflection.'))
        '''

    def _initiating(self):
        return self._activity.initiating

    def new_game(self, orientation='horizontal'):
        ''' Start a new game. '''
        self._orientation = orientation

        self._all_clear()

        # Fill in a few dots to start
        for i in range(int(TEN * SIX / 2)):
            n = int(uniform(0, TEN * SIX))
            if self.roygbiv:
                self._dots[n].type = int(uniform(2, len(self._colors)))
            else:
                self._dots[n].type = int(uniform(0, 4))
            self._dots[n].set_shape(self._new_dot(
                    self._colors[self._dots[n].type]))

        if self.we_are_sharing:
            _logger.debug('sending a new game')
            self._parent.send_new_game()

    def restore_game(self, dot_list, orientation):
        ''' Restore a game from the Journal or share '''
        for i, dot in enumerate(dot_list):
            self._dots[i].type = dot
            self._dots[i].set_shape(self._new_dot(
                    self._colors[self._dots[i].type]))
        self._orientation = orientation
        self._set_orientation()

    def save_game(self):
        ''' Return dot list and orientation for saving to Journal or
        sharing '''
        dot_list = []
        for dot in self._dots:
            dot_list.append(dot.type)
        return [dot_list, self._orientation]

    def _set_label(self, string):
        ''' Set the label in the toolbar or the window frame. '''
        self._activity.status.set_label(string)

    def _button_press_cb(self, win, event):
        win.grab_focus()
        x, y = map(int, event.get_coords())
        self._press = True

        spr = self._sprites.find_sprite((x, y))
        if spr == None:
            return True

        self.last_spr = spr
        if spr.type is not None:
            if not self._timer is None:
                GObject.source_remove(self._timer)
            self._increment_dot(spr)
        return True

    def _button_release_cb(self, win, event):
        self._press = False
        if not self._timer is None:
            GObject.source_remove(self._timer)

    def _increment_dot(self, spr):
        spr.type += 1
        if self.roygbiv:
            if spr.type >= len(self._colors):
                spr.type = 2
        else:
            spr.type %= 4
        spr.set_shape(self._new_dot(self._colors[spr.type]))

        if self.playing_with_robot:
            self._robot_play(spr)

        self._test_game_over()

        if self.we_are_sharing:
            _logger.debug('sending a click to the share')
            self._parent.send_dot_click(self._dots.index(spr), spr.type)

        self._timer = GObject.timeout_add(1000, self._increment_dot, spr)

    def _mouse_move_cb(self, win, event):
        """ Drag a tile with the mouse. """
        if not self._press:
            return
        x, y = map(int, event.get_coords())
        spr = self._sprites.find_sprite((x, y))
        if spr == self.last_spr:
            return True
        if spr is None:
            return True
        if spr.type is not None:
            self.last_spr = spr
            if not self._timer is None:
                GObject.source_remove(self._timer)
            self._increment_dot(spr)

    def _robot_play(self, dot):
        ''' Robot reflects dot clicked. '''
        x, y = self._dot_to_grid(self._dots.index(dot))
        if self._orientation == 'horizontal':
            x = TEN - x - 1
            i = self._grid_to_dot((x, y))
            self._dots[i].type = dot.type
            self._dots[i].set_shape(self._new_dot(self._colors[dot.type]))
            if self.we_are_sharing:
                _logger.debug('sending a robot click to the share')
                self._parent.send_dot_click(i, dot.type)
        elif self._orientation == 'vertical':
            y = SIX - y - 1
            i = self._grid_to_dot((x, y))
            self._dots[i].type = dot.type
            self._dots[i].set_shape(self._new_dot(self._colors[dot.type]))
            if self.we_are_sharing:
                _logger.debug('sending a robot click to the share')
                self._parent.send_dot_click(i, dot.type)
        else:
            x = TEN - x - 1
            i = self._grid_to_dot((x, y))
            self._dots[i].type = dot.type
            self._dots[i].set_shape(self._new_dot(self._colors[dot.type]))
            if self.we_are_sharing:
                _logger.debug('sending a robot click to the share')
                self._parent.send_dot_click(i, dot.type)
            y = SIX - y - 1
            i = self._grid_to_dot((x, y))
            self._dots[i].type = dot.type
            self._dots[i].set_shape(self._new_dot(self._colors[dot.type]))
            if self.we_are_sharing:
                _logger.debug('sending a robot click to the share')
                self._parent.send_dot_click(i, dot.type)
            x = TEN - x - 1
            i = self._grid_to_dot((x, y))
            self._dots[i].type = dot.type
            self._dots[i].set_shape(self._new_dot(self._colors[dot.type]))
            if self.we_are_sharing:
                _logger.debug('sending a robot click to the share')
                self._parent.send_dot_click(i, dot.type)

    def remote_button_press(self, dot, color):
        ''' Receive a button press from a sharer '''
        self._dots[dot].type = color
        self._dots[dot].set_shape(self._new_dot(self._colors[color]))

    def set_sharing(self, share=True):
        _logger.debug('enabling sharing')
        self.we_are_sharing = share

    def _smile(self):
        for dot in self._dots:
            dot.set_label(':)')

    def _test_game_over(self):
        ''' Check to see if game is over '''
        if self._orientation == 'horizontal':
            for y in range(SIX):
                for x in range(SIX):
                    if self._dots[y * TEN + x].type != \
                            self._dots[y * TEN + TEN - x - 1].type:
                        self._set_label(_('keep trying'))
                        return False
            self._set_label(_('good work'))
            self._smile()
            return True
        if self._orientation == 'vertical':
            for y in range(int(SIX / 2)):
                for x in range(TEN):
                    if self._dots[y * TEN + x].type != \
                            self._dots[(SIX - y - 1) * TEN + x].type:
                        self._set_label(_('keep trying'))
                        return False
            self._set_label(_('good work'))
        else:
            for y in range(SIX):
                for x in range(SIX):
                    if self._dots[y * TEN + x].type != \
                            self._dots[y * TEN + TEN - x - 1].type:
                        self._set_label(_('keep trying'))
                        return False
            for y in range(int(SIX / 2)):
                for x in range(TEN):
                    if self._dots[y * TEN + x].type != \
                            self._dots[(SIX - y - 1) * TEN + x].type:
                        self._set_label(_('keep trying'))
                        return False
            self._set_label(_('good work'))
        self._smile()
        return True
    def __draw_cb(self,canvas,cr):
		self._sprites.redraw_sprites(cr=cr)
    def _grid_to_dot(self, pos):
        ''' calculate the dot index from a column and row in the grid '''
        return pos[0] + pos[1] * TEN

    def _dot_to_grid(self, dot):
        ''' calculate the grid column and row for a dot '''
        return [dot % TEN, int(dot / TEN)]

    def _expose_cb(self, win, event):
        self.do_expose_event(event)

    def do_expose_event(self, event):
        ''' Handle the expose-event by drawing '''
        # Restrict Cairo to the exposed area
        cr = self._canvas.window.cairo_create()
        cr.rectangle(event.area.x, event.area.y,
                event.area.width, event.area.height)
        cr.clip()
        # Refresh sprite list
        self._sprites.redraw_sprites(cr=cr)

    def _destroy_cb(self, win, event):
        Gtk.main_quit()

    def _new_dot(self, color):
        ''' generate a dot of a color color '''
        self._dot_cache = {}
        if not color in self._dot_cache:
            self._stroke = color
            self._fill = color
            self._svg_width = self._dot_size
            self._svg_height = self._dot_size
            pixbuf = svg_str_to_pixbuf(
                self._header() + \
                self._circle(self._dot_size / 2., self._dot_size / 2.,
                             self._dot_size / 2.) + \
                self._footer())

            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                         self._svg_width, self._svg_height)
            context = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
            context.rectangle(0, 0, self._svg_width, self._svg_height)
            context.fill()
            self._dot_cache[color] = surface

        return self._dot_cache[color]

    def _line(self, vertical=True):
        ''' Generate a center line '''
        if vertical:
            self._svg_width = 3
            self._svg_height = self._height
            return svg_str_to_pixbuf(
                self._header() + \
                self._rect(3, self._height, 0, 0) + \
                self._footer())
        else:
            self._svg_width = self._width
            self._svg_height = 3
            return svg_str_to_pixbuf(
                self._header() + \
                self._rect(self._width, 3, 0, 0) + \
                self._footer())

    def _header(self):
        return '<svg\n' + 'xmlns:svg="http://www.w3.org/2000/svg"\n' + \
            'xmlns="http://www.w3.org/2000/svg"\n' + \
            'xmlns:xlink="http://www.w3.org/1999/xlink"\n' + \
            'version="1.1"\n' + 'width="' + str(self._svg_width) + '"\n' + \
            'height="' + str(self._svg_height) + '">\n'

    def _rect(self, w, h, x, y):
        svg_string = '       <rect\n'
        svg_string += '          width="%f"\n' % (w)
        svg_string += '          height="%f"\n' % (h)
        svg_string += '          rx="%f"\n' % (0)
        svg_string += '          ry="%f"\n' % (0)
        svg_string += '          x="%f"\n' % (x)
        svg_string += '          y="%f"\n' % (y)
        svg_string += 'style="fill:#000000;stroke:#000000;"/>\n'
        return svg_string

    def _circle(self, r, cx, cy):
        return '<circle style="fill:' + str(self._fill) + ';stroke:' + \
            str(self._stroke) + ';" r="' + str(r - 0.5) + '" cx="' + \
            str(cx) + '" cy="' + str(cy) + '" />\n'

    def _footer(self):
        return '</svg>\n'


def svg_str_to_pixbuf(svg_string):
    try:
        pl = GdkPixbuf.PixbufLoader.new_with_type('svg')
        pl.write(svg_string)
        pl.close()
        pixbuf = pl.get_pixbuf()
        return pixbuf
    except:
        print svg_string
        return None

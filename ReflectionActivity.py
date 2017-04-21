#Copyright (c) 2011 Walter Bender
#Copyright (c) 2012 Ignacio Rodriguez

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


from gi.repository import Gtk,Gdk
from sugar3.activity import activity
from sugar3 import profile
try:
    from sugar3.graphics.toolbarbox import ToolbarBox
    _have_toolbox = True
except ImportError:
    _have_toolbox = False

if _have_toolbox:
    from sugar3.activity.widgets import ActivityToolbarButton
    from sugar3.activity.widgets import StopButton

from toolbar_utils import button_factory, label_factory, separator_factory, \
                          radio_factory
from utils import json_load, json_dump

import telepathy
import dbus
from dbus.service import signal
from dbus.gobject_service import ExportedGObject
from sugar3.presence import presenceservice
from sugar3.presence.tubeconn import TubeConnection

from gettext import gettext as _

from game import Game

import logging
_logger = logging.getLogger('reflection-activity')


SERVICE = 'org.sugarlabs.ReflectionActivity'
IFACE = SERVICE
PATH = '/org/augarlabs/ReflectionActivity'


class ReflectionActivity(activity.Activity):
    """ Reflection puzzle game """

    def __init__(self, handle):
        """ Initialize the toolbars and the game board """
        try:
            super(ReflectionActivity, self).__init__(handle)
        except dbus.exceptions.DBusException, e:
            _logger.error(str(e))

        self.nick = profile.get_nick_name()
        if profile.get_color() is not None:
            self.colors = profile.get_color().to_string().split(',')
        else:
            self.colors = ['#A0FFA0', '#FF8080']

        self._setup_toolbars(_have_toolbox)
        self._setup_dispatch_table()

        # Create a canvas
        canvas = Gtk.DrawingArea()
        canvas.set_size_request(Gdk.Screen.width(), \
                                Gdk.Screen.height())
        self.set_canvas(canvas)
        canvas.show()
        self.show_all()

        self._game = Game(canvas, parent=self, colors=self.colors)
        self._setup_presence_service()

        if 'dotlist' in self.metadata:
            self._restore()
        else:
            self._game.new_game('horizontal')

    def _setup_toolbars(self, have_toolbox):
        """ Setup the toolbars. """

        self.max_participants = 4

        if have_toolbox:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button, 0)
            activity_button.show()

            self.set_toolbar_box(toolbox)
            toolbox.show()
            self.toolbar = toolbox.toolbar

        else:
            # Use pre-0.86 toolbar design
            games_toolbar = Gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Game'), games_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = games_toolbar

        my_colors = radio_factory(
            'my-colors', self.toolbar, self._my_colors_cb, group=None)

        radio_factory('toolbar-colors', self.toolbar,
                      self._roygbiv_colors_cb, group=my_colors)

        self._new_game_button_h = button_factory(
            'new-game-horizontal', self.toolbar, self._new_game_cb,
            cb_arg='horizontal',
            tooltip=_('Start a new horizontal-reflection game.'))

        self._new_game_button_v = button_factory(
            'new-game-vertical', self.toolbar, self._new_game_cb,
            cb_arg='vertical',
            tooltip=_('Start a new vertical-reflection game.'))

        self._new_game_button_b = button_factory(
            'new-game-bilateral', self.toolbar, self._new_game_cb,
            cb_arg='bilateral',
            tooltip=_('Start a new bilateral-reflection game.'))

        self.status = label_factory(self.toolbar, '')

        if _have_toolbox:
            separator_factory(toolbox.toolbar, False, True)

        self.robot_button = button_factory(
            'robot-off', self.toolbar, self._robot_cb,
            tooltip= _('Play with the robot.'))

        if _have_toolbox:
            separator_factory(toolbox.toolbar, True, False)

        if _have_toolbox:
            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _my_colors_cb(self, button=None):
        if hasattr(self, '_game'):
            self._game.roygbiv = False
            self._game.new_game()

    def _roygbiv_colors_cb(self, button=None):
        if hasattr(self, '_game'):
            self._game.roygbiv = True
            self._game.new_game()

    def _new_game_cb(self, button=None, orientation='horizontal'):
        ''' Start a new game. '''
        self._game.new_game(orientation)

    def _robot_cb(self, button=None):
        ''' Play with the computer (or not). '''
        if not self._game.playing_with_robot:
            self.set_robot_status(True, 'robot-on')
        else:
            self.set_robot_status(False, 'robot-off')

    def set_robot_status(self, status, icon):
        ''' Reset robot icon and status '''
        self._game.playing_with_robot = status
        self.robot_button.set_icon_name(icon)

    def write_file(self, file_path):
        """ Write the grid status to the Journal """
        [dot_list, orientation] = self._game.save_game()
        self.metadata['orientation'] = orientation
        self.metadata['dotlist'] = ''
        for dot in dot_list:
            self.metadata['dotlist'] += str(dot)
            if dot_list.index(dot) < len(dot_list) - 1:
                self.metadata['dotlist'] += ' '

    def _restore(self):
        """ Restore the game state from metadata """
        if 'orientation' in self.metadata:
            orientation = self.metadata['orientation']
        else:
            orientation = 'horizontal'

        dot_list = []
        dots = self.metadata['dotlist'].split()
        for dot in dots:
            dot_list.append(int(dot))
        self._game.restore_game(dot_list, orientation)

    # Collaboration-related methods

    def _setup_presence_service(self):
        """ Setup the Presence Service. """
        self.pservice = presenceservice.get_instance()
        self.initiating = None  # sharing (True) or joining (False)

        owner = self.pservice.get_owner()
        self.owner = owner
        self._share = ""
        self.connect('shared', self._shared_cb)
        self.connect('joined', self._joined_cb)

    def _shared_cb(self, activity):
        """ Either set up initial share..."""
        self._new_tube_common(True)

    def _joined_cb(self, activity):
        """ ...or join an exisiting share. """
        self._new_tube_common(False)

    def _new_tube_common(self, sharer):
        """ Joining and sharing are mostly the same... """
        if self._shared_activity is None:
            _logger.debug("Error: Failed to share or join activity ... \
                _shared_activity is null in _shared_cb()")
            return

        self.initiating = sharer
        self.waiting_for_hand = not sharer

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        if sharer:
            _logger.debug('This is my activity: making a tube...')
            id = self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].OfferDBusTube(
                SERVICE, {})
        else:
            _logger.debug('I am joining an activity: waiting for a tube...')
            self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
                reply_handler=self._list_tubes_reply_cb,
                error_handler=self._list_tubes_error_cb)
        self._game.set_sharing(True)

    def _list_tubes_reply_cb(self, tubes):
        """ Reply to a list request. """
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        """ Log errors. """
        _logger.debug('Error: ListTubes() failed: %s' % (e))

    def _new_tube_cb(self, id, initiator, type, service, params, state):
        """ Create a new tube. """
        _logger.debug('New tube: ID=%d initator=%d type=%d service=%s \
params=%r state=%d' % (id, initiator, type, service, params, state))

        if (type == telepathy.TUBE_TYPE_DBUS and service == SERVICE):
            if state == telepathy.TUBE_STATE_LOCAL_PENDING:
                self.tubes_chan[ \
                              telepathy.CHANNEL_TYPE_TUBES].AcceptDBusTube(id)

            tube_conn = TubeConnection(self.conn,
                self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES], id, \
                group_iface=self.text_chan[telepathy.CHANNEL_INTERFACE_GROUP])

            self.chattube = ChatTube(tube_conn, self.initiating, \
                self.event_received_cb)

    def _setup_dispatch_table(self):
        ''' Associate tokens with commands. '''
        self._processing_methods = {
            'n': [self._receive_new_game, 'get a new game grid'],
            'p': [self._receive_dot_click, 'get a dot click'],
            }

    def event_received_cb(self, event_message):
        ''' Data from a tube has arrived. '''
        if len(event_message) == 0:
            return
        try:
            command, payload = event_message.split('|', 2)
        except ValueError:
            _logger.debug('Could not split event message %s' % (event_message))
            return
        self._processing_methods[command][0](payload)

    def send_new_game(self):
        ''' Send a new orientation, grid to all players '''
        self.send_event('n|%s' % (json_dump(self._game.save_game())))

    def _receive_new_game(self, payload):
        ''' Sharer can start a new game. '''
        [dot_list, orientation] = json_load(payload)
        self._game.restore_game(dot_list, orientation)

    def send_dot_click(self, dot, color):
        ''' Send a dot click to all the players '''
        self.send_event('p|%s' % (json_dump([dot, color])))

    def _receive_dot_click(self, payload):
        ''' When a dot is clicked, everyone should change its color. '''
        (dot, color) = json_load(payload)
        self._game.remote_button_press(dot, color)

    def send_event(self, entry):
        """ Send event through the tube. """
        if hasattr(self, 'chattube') and self.chattube is not None:
            self.chattube.SendText(entry)


class ChatTube(ExportedGObject):
    """ Class for setting up tube for sharing """

    def __init__(self, tube, is_initiator, stack_received_cb):
        super(ChatTube, self).__init__(tube, PATH)
        self.tube = tube
        self.is_initiator = is_initiator  # Are we sharing or joining activity?
        self.stack_received_cb = stack_received_cb
        self.stack = ''

        self.tube.add_signal_receiver(self.send_stack_cb, 'SendText', IFACE,
                                      path=PATH, sender_keyword='sender')

    def send_stack_cb(self, text, sender=None):
        if sender == self.tube.get_unique_name():
            return
        self.stack = text
        self.stack_received_cb(text)

    @signal(dbus_interface=IFACE, signature='s')
    def SendText(self, text):
        self.stack = text

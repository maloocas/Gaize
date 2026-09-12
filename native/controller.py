#!/usr/bin/env python3
"""Native macOS eye controller: webcam gaze moves the pointer, eye gestures click.

  * Look to move the pointer (gaze_engine.py, calibrated at launch).
  * Hard blink (squeeze or hold both eyes a little) selects the accessibility
    target nearest the gaze. One target in range is selected directly; several
    open a zoomed view where another hard blink picks one.
  * Wink left / right clicks the selected target, or the pointer if none.
  * Natural blinks do nothing, except in the keyboard where they end a swiped
    word. Looking at the top strip of the keyboard finishes the sentence and
    sends it to the LLM.
"""

from __future__ import annotations

import collections
import atexit
import os
import json
from pathlib import Path
import statistics
import threading
import time

import AppKit
import AVFoundation
from Foundation import NSData, NSObject, NSString, NSTimer
import cv2
import objc
import Quartz

from accessibility_targets import discover_targets
from autocomplete import Autocomplete
from blink_gestures import GestureDetector
from bridge import click, insert_text, post_click, press_return, screen_size
from llm import decode_sentence, fallback
from snapping import SNAP_RADIUS, candidates, center, pick, to_zoom, zoom_dest, zoom_region
from swipe_decoder import SwipeDecoder
from swipe_session import SwipeSession


# One shared HID-state event source for every synthetic mouse event.
# Posting a button-down with source=None leaves the HID system believing no
# button is held, so when the user then moves the pointer the system emits
# MouseMoved rather than LeftMouseDragged and the drag never happens. Driving
# press, drag and release from a single HID-state source keeps that state
# coherent, which is what makes dragging work at all.
EVENT_SOURCE = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

KEY_RADIUS = 12.0
SCROLL_DWELL_SECONDS = 0.65
SELECTION_TIMEOUT = 8.0
EXIT_STRIP_SHARE = 0.22      # share of the keyboard's height

# Calibration: the four corners, then the center. Kept short for now; add
# points here (and VAL_POINTS for a bias check) when accuracy matters more.
FREEZE_CLOSURE = 0.10   # either eye above this holds the pointer still
CALIBRATION_FILE = Path.home()/"Library"/"Application Support"/"OpenGaze"/"calibration.pkl"
# 17 points: an even 4x4 grid spanning the screen (outer dots ~30pt from
# each edge), then the center.
_XS = [.02 + i * (.96 / 3) for i in range(4)]
_YS = [.032 + i * (.936 / 3) for i in range(4)]
CAL_POINTS = [(x, y) for y in _YS for x in _XS] + [(.5, .5)]
VAL_POINTS = []
# Eye naming: set OPENGAZE_SWAP_EYES=1 if winks click the wrong button.
SWAP_EYES = os.environ.get("OPENGAZE_SWAP_EYES") == "1"
SETTLE_SECONDS = .9          # eyes travel to the dot before capture starts
CAPTURE_SECONDS = 1.2
WINK_TEST_SECONDS = 2.5


def quartz_cursor():
    """Current pointer position in QUARTZ coordinates (origin top-left).

    macOS has two conflicting conventions and mixing them is invisible until it
    is catastrophic: NSEvent.mouseLocation() is Cocoa (origin BOTTOM-left, y up)
    while CGEventCreateMouseEvent interprets its point as Quartz (origin
    TOP-left, y down). Feeding a Cocoa point to a CGEvent mirrors it vertically
    - on a 982pt display a click near the top landed 682pt away near the bottom,
    dragging whatever was grabbed to the wrong end of the screen and leaving the
    drawn reticle and the real cursor in two different places.

    Anything posted as a CGEvent must use this. Anything positioning an NSWindow
    must use NSEvent.mouseLocation() instead.
    """
    return Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))


def move_pointer(x, y, dragging=False):
    """Move the real pointer to a Quartz point, as a genuine mouse event so
    hover states and tracking areas update."""
    kind = Quartz.kCGEventLeftMouseDragged if dragging else Quartz.kCGEventMouseMoved
    event = Quartz.CGEventCreateMouseEvent(EVENT_SOURCE, kind, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def camera_choice():
    """(OpenCV index, name) of the camera to use.

    Prefers an iPhone via Continuity Camera, which streams the phone's back
    camera: far better eye detail than a laptop webcam. OPENGAZE_CAMERA picks
    another camera by index or by part of its name. OpenCV numbers cameras in
    AVCaptureDevice order, so the index is the position in that list.
    """
    devices=[str(d.localizedName()) for d in
             AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)]
    wanted=os.environ.get("OPENGAZE_CAMERA","").strip()
    if wanted.isdigit() and int(wanted)<len(devices):
        return int(wanted),devices[int(wanted)]
    for pattern in ([wanted.lower()] if wanted else [])+["iphone","continuity"]:
        for i,name in enumerate(devices):
            if pattern in name.lower(): return i,name
    return 0,(devices[0] if devices else "default")


PID_FILE = Path("/private/tmp/opengaze.pid")
SWIPE_WORDS = Path(__file__).with_name("swipe_words.txt")
REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_FILE = REPO_ROOT / "data" / "corpus.txt"
PROFILE_FILE = REPO_ROOT / "data" / "profile.json"


def _label(text, point, size=18, color=None, bold=True):
    attrs = {AppKit.NSFontAttributeName:
                 AppKit.NSFont.boldSystemFontOfSize_(size) if bold
                 else AppKit.NSFont.systemFontOfSize_(size),
             AppKit.NSForegroundColorAttributeName: color or AppKit.NSColor.whiteColor()}
    NSString.stringWithString_(text).drawAtPoint_withAttributes_(point, attrs)


def _centered_label(text, bounds, size, color=None):
    attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(size),
             AppKit.NSForegroundColorAttributeName: color or AppKit.NSColor.whiteColor()}
    label = NSString.stringWithString_(text)
    s = label.sizeWithAttributes_(attrs)
    label.drawAtPoint_withAttributes_(
        (bounds.origin.x + (bounds.size.width - s.width) / 2,
         bounds.origin.y + (bounds.size.height - s.height) / 2), attrs)


class CrosshairView(AppKit.NSView):
    controller = objc.ivar()

    def initWithController_(self, controller):
        self=objc.super(CrosshairView,self).initWithFrame_(((0,0),(52,52)))
        if self is not None: self.controller=controller
        return self

    def drawRect_(self, _rect):
        center=26
        c=self.controller
        color=(AppKit.NSColor.colorWithWhite_alpha_(.72,.95)
               if getattr(c,"paused",False) else
               AppKit.NSColor.colorWithRed_green_blue_alpha_(.82,.38,1,.98)
               if c.drag_mode else
               AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.12,.98)
               if time.monotonic()<c.click_flash_until else
               AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.55,.15,.98)
               if getattr(c,"gaze_drift",False)
               else AppKit.NSColor.colorWithRed_green_blue_alpha_(.1,.9,1,.95))
        AppKit.NSColor.colorWithWhite_alpha_(1,.13).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((4,4),(44,44)),14,14).fill()
        color.setStroke()
        ring=AppKit.NSBezierPath.bezierPathWithOvalInRect_(((10,10),(32,32)))
        ring.setLineWidth_(3); ring.stroke()
        for start,end in (((center,1),(center,17)),((center,35),(center,51)),
                          ((1,center),(17,center)),((35,center),(51,center))):
            line=AppKit.NSBezierPath.bezierPath(); line.moveToPoint_(start); line.lineToPoint_(end)
            line.setLineWidth_(3); line.stroke()
        # The dot turns yellow while the eyes are closing, so the user can see
        # a gesture is being read before it fires.
        (AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.12,1)
         if getattr(c,"eyes_closing",False) else AppKit.NSColor.whiteColor()).setFill()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(((22,22),(8,8))).fill()


class SwipeTraceView(AppKit.NSView):
    controller=objc.ivar()

    def initWithController_frame_(self,controller,frame):
        self=objc.super(SwipeTraceView,self).initWithFrame_(frame)
        if self is not None: self.controller=controller
        return self

    def hitTest_(self,_point):
        return None

    def drawRect_(self,_rect):
        points=self.controller.swipe_path
        if not self.controller.swipe_recording or len(points)<2: return
        path=AppKit.NSBezierPath.bezierPath(); path.moveToPoint_(points[0])
        for point in points[1:]: path.lineToPoint_(point)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.15,.85,1,.78).setStroke()
        path.setLineWidth_(7); path.setLineCapStyle_(AppKit.NSLineCapStyleRound); path.stroke()


class ExitStripView(AppKit.NSView):
    """The top band of the keyboard: looking into it finishes the sentence."""
    controller=objc.ivar()

    def initWithController_frame_(self,controller,frame):
        self=objc.super(ExitStripView,self).initWithFrame_(frame)
        if self is not None: self.controller=controller
        return self

    def hitTest_(self,_point):
        return None

    def drawRect_(self,_rect):
        bounds=self.bounds()
        hover=getattr(self.controller,"exit_hover",False)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            *((.20,.62,.40,.95) if hover else (.12,.30,.24,.90))).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSInsetRect(bounds,10,8),20,20).fill()
        _centered_label("LOOK HERE TO FINISH THE SENTENCE",bounds,34)


class KeyView(AppKit.NSView):
    """A single keyboard key, drawn by hand.

    The stock NSButton bezel is a small grey Aqua control: wrong shape, wrong
    contrast and far too timid for a key someone aims at with their eyes. These
    draw as large high-contrast slabs that light up under the pointer, so the
    user can see what they are about to hit before they commit to it.
    """
    controller=objc.ivar(); keyValue=objc.ivar(); keyTitle=objc.ivar()
    accent=objc.ivar(); hovering=objc.ivar(); pressed=objc.ivar()

    def initWithFrame_controller_title_value_accent_(self,frame,controller,title,value,accent):
        self=objc.super(KeyView,self).initWithFrame_(frame)
        if self is None: return None
        self.controller=controller; self.keyTitle=title; self.keyValue=value
        self.accent=int(accent); self.hovering=False; self.pressed=False
        return self

    def updateTrackingAreas(self):
        for area in self.trackingAreas(): self.removeTrackingArea_(area)
        self.addTrackingArea_(
            AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(),
                AppKit.NSTrackingMouseEnteredAndExited
                | AppKit.NSTrackingActiveAlways
                | AppKit.NSTrackingInVisibleRect,
                self, None))

    def acceptsFirstMouse_(self,_event):
        # Our app is intentionally never active, so without this the click that
        # would normally just focus the window gets swallowed instead of
        # pressing the key.
        return True

    def mouseEntered_(self,_event):
        self.hovering=True; self.setNeedsDisplay_(True)

    def mouseExited_(self,_event):
        self.hovering=False; self.setNeedsDisplay_(True)

    def mouseDown_(self,_event):
        self.pressed=True; self.setNeedsDisplay_(True)

    def mouseUp_(self,_event):
        self.pressed=False; self.setNeedsDisplay_(True)
        self.controller.keyPressed_(self.keyValue)

    def drawRect_(self,_rect):
        bounds=self.bounds()
        path=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSInsetRect(bounds,2,2),KEY_RADIUS,KEY_RADIUS)
        if self.pressed:      fill=(.40,.85,1,1.0)
        elif self.hovering:   fill=(.30,.72,.98,.85)
        elif self.accent==2:  fill=(.18,.42,.72,.92)   # deliver the text
        elif self.accent:     fill=(.17,.72,.42,.92)   # deliver it and send
        else:                 fill=(.16,.22,.30,.95)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(*fill).setFill(); path.fill()
        AppKit.NSColor.colorWithWhite_alpha_(1,.92 if self.hovering else .42).setStroke()
        path.setLineWidth_(2); path.stroke()

        long_label=len(str(self.keyValue))!=1
        size=min(20 if long_label else 44,bounds.size.height*.45)
        attrs={AppKit.NSFontAttributeName:
                   AppKit.NSFont.systemFontOfSize_weight_(size,AppKit.NSFontWeightSemibold),
               AppKit.NSForegroundColorAttributeName:
                   AppKit.NSColor.colorWithWhite_alpha_(.06,1) if self.pressed
                   else AppKit.NSColor.whiteColor()}
        label=NSString.stringWithString_(self.keyTitle)
        size=label.sizeWithAttributes_(attrs)
        label.drawAtPoint_withAttributes_(
            ((bounds.size.width-size.width)/2,(bounds.size.height-size.height)/2),attrs)


class SafetyKeyView(KeyView):
    """Large, persistent pause/stop target that remains usable while paused."""

    def drawRect_(self,_rect):
        bounds=self.bounds()
        path=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSInsetRect(bounds,2,2),14,14)
        danger=str(self.keyValue)=="EMERGENCY_STOP"
        if self.pressed:    fill=(1,.78,.20,1) if not danger else (1,.28,.24,1)
        elif self.hovering: fill=(.35,.78,1,.95) if not danger else (1,.25,.22,.95)
        elif danger:        fill=(.72,.10,.12,.94)
        else:               fill=(.10,.42,.62,.94)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(*fill).setFill(); path.fill()
        AppKit.NSColor.colorWithWhite_alpha_(1,.92 if self.hovering else .48).setStroke()
        path.setLineWidth_(2); path.stroke()
        attrs={AppKit.NSFontAttributeName:
                   AppKit.NSFont.systemFontOfSize_weight_(16,AppKit.NSFontWeightBold),
               AppKit.NSForegroundColorAttributeName:AppKit.NSColor.whiteColor()}
        label=NSString.stringWithString_(self.keyTitle)
        size=label.sizeWithAttributes_(attrs)
        label.drawAtPoint_withAttributes_(
            ((bounds.size.width-size.width)/2,(bounds.size.height-size.height)/2),attrs)


class ScrollZoneView(AppKit.NSView):
    """A large edge target that shows dwell progress before scrolling."""
    controller=objc.ivar(); direction=objc.ivar()

    def initWithFrame_controller_direction_(self,frame,controller,direction):
        self=objc.super(ScrollZoneView,self).initWithFrame_(frame)
        if self is not None:
            self.controller=controller; self.direction=int(direction)
        return self

    def drawRect_(self,_rect):
        bounds=self.bounds()
        active=(self.controller.scroll_active_direction==self.direction)
        hovering=(self.controller.scroll_hover_direction==self.direction)
        path=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSInsetRect(bounds,2,2),18,18)
        fill=((.12,.72,.48,.92) if active else
              (.12,.52,.72,.82) if hovering else (.10,.16,.23,.72))
        AppKit.NSColor.colorWithRed_green_blue_alpha_(*fill).setFill(); path.fill()
        AppKit.NSColor.colorWithWhite_alpha_(1,.85 if hovering else .35).setStroke()
        path.setLineWidth_(2); path.stroke()
        arrow="▲" if self.direction>0 else "▼"
        attrs={AppKit.NSFontAttributeName:
                   AppKit.NSFont.systemFontOfSize_weight_(34,AppKit.NSFontWeightBold),
               AppKit.NSForegroundColorAttributeName:AppKit.NSColor.whiteColor()}
        label=NSString.stringWithString_(arrow)
        size=label.sizeWithAttributes_(attrs)
        label.drawAtPoint_withAttributes_(
            ((bounds.size.width-size.width)/2,(bounds.size.height-size.height)/2+8),attrs)
        caption=NSString.stringWithString_("SCROLL")
        small={AppKit.NSFontAttributeName:AppKit.NSFont.boldSystemFontOfSize_(11),
               AppKit.NSForegroundColorAttributeName:
                   AppKit.NSColor.colorWithWhite_alpha_(1,.82)}
        cap_size=caption.sizeWithAttributes_(small)
        caption.drawAtPoint_withAttributes_(((bounds.size.width-cap_size.width)/2,15),small)
        if hovering and not active:
            progress=max(0.0,min(1.0,self.controller.scroll_dwell_progress))
            AppKit.NSColor.colorWithRed_green_blue_alpha_(.20,.88,1,.98).setFill()
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                ((8,7),((bounds.size.width-16)*progress,5)),2.5,2.5).fill()


class TargetOverlayView(AppKit.NSView):
    """Click-through outlines for controls exposed by macOS Accessibility,
    plus a heavy highlight on the currently selected one."""
    controller=objc.ivar()

    def initWithController_frame_(self,controller,frame):
        self=objc.super(TargetOverlayView,self).initWithFrame_(frame)
        if self is not None: self.controller=controller
        return self

    def hitTest_(self,_point):
        return None

    @objc.python_method
    def _rect(self,target):
        screen=self.controller.target_overlay_screen
        x=target["x"]-screen.origin.x
        y=screen.size.height-(target["y"]+target["height"])+screen.origin.y
        return ((x,y),(target["width"],target["height"]))

    def drawRect_(self,_rect):
        selected=getattr(self.controller,"selected_target",None)
        # Debug: every target thin grey, the ones a hard blink would consider
        # thick green, and the snap radius R as a circle around the pointer.
        p=quartz_cursor()
        near=candidates(self.controller.accessibility_targets,p.x,p.y)
        for target in self.controller.accessibility_targets:
            inside=any(t is target for t in near)
            (AppKit.NSColor.colorWithRed_green_blue_alpha_(.2,1,.3,1) if inside else
             AppKit.NSColor.colorWithRed_green_blue_alpha_(.2,.8,1,.8)).setStroke()
            box=AppKit.NSBezierPath.bezierPathWithRect_(self._rect(target))
            box.setLineWidth_(4 if inside else 2); box.stroke()
        # Click markers: blue L / red R ring where each click landed, fading.
        now=time.monotonic()
        self.controller.click_marks=[m for m in self.controller.click_marks if now-m[3]<.8]
        for kind,mx,my,at in self.controller.click_marks:
            age=(now-at)/.8
            x=mx-self.controller.target_overlay_screen.origin.x
            y=self.controller.target_overlay_screen.size.height-my+self.controller.target_overlay_screen.origin.y
            r=14+30*age
            (AppKit.NSColor.colorWithRed_green_blue_alpha_(.2,.5,1,1-age) if kind=="L" else
             AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.2,.2,1-age)).setStroke()
            mark=AppKit.NSBezierPath.bezierPathWithOvalInRect_(((x-r,y-r),(2*r,2*r)))
            mark.setLineWidth_(5); mark.stroke()
            _label(kind,(x-7,y-10),22)
        screen=self.controller.target_overlay_screen
        cx=p.x-screen.origin.x; cy=screen.size.height-p.y+screen.origin.y
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.3,.8,.9).setStroke()
        ring=AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            ((cx-SNAP_RADIUS,cy-SNAP_RADIUS),(2*SNAP_RADIUS,2*SNAP_RADIUS)))
        ring.setLineWidth_(2); ring.stroke()
        if self.controller.target_boxes_enabled:
            colors={
                "text":AppKit.NSColor.colorWithRed_green_blue_alpha_(.18,.88,1,.92),
                "navigation":AppKit.NSColor.colorWithRed_green_blue_alpha_(.72,.42,1,.92),
                "setting":AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.72,.18,.92),
                "action":AppKit.NSColor.colorWithRed_green_blue_alpha_(.25,1,.55,.92),
            }
            for target in self.controller.accessibility_targets:
                rect=self._rect(target)
                if not AppKit.NSIntersectsRect(rect,self.bounds()): continue
                color=colors.get(target["kind"],colors["action"])
                color.setStroke()
                box=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    AppKit.NSInsetRect(rect,-2,-2),7,7)
                box.setLineWidth_(2.5); box.stroke()
        if selected is not None:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.85,.1,1).setStroke()
            box=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AppKit.NSInsetRect(self._rect(selected),-6,-6),10,10)
            box.setLineWidth_(6); box.stroke()


class ZoomView(AppKit.NSView):
    """Magnified view of the area around several nearby targets.

    Drawn full screen; the pointer (still gaze-driven) hovers a zoomed target
    and a hard blink chooses it. Falls back to labelled boxes when the screen
    cannot be captured (no Screen Recording permission)."""
    controller=objc.ivar()

    def initWithController_frame_(self,controller,frame):
        self=objc.super(ZoomView,self).initWithFrame_(frame)
        if self is not None: self.controller=controller
        return self

    def hitTest_(self,_point):
        return None

    def drawRect_(self,_rect):
        zoom=self.controller.zoom
        if not zoom: return
        height=self.bounds().size.height
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.02,.03,.05,.94).setFill()
        AppKit.NSBezierPath.fillRect_(self.bounds())
        dx,dy,dw,dh=zoom["dest"]
        if zoom["image"] is not None:
            zoom["image"].drawInRect_(((dx,height-dy-dh),(dw,dh)))
        p=quartz_cursor()
        hovered=pick(zoom["targets"],p.x,p.y)
        for target in zoom["targets"]:
            rect=((target["x"],height-target["y"]-target["height"]),
                  (target["width"],target["height"]))
            active=target is hovered
            if zoom["image"] is None:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(.12,.18,.26,.95).setFill()
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect,10,10).fill()
                _centered_label(str(target.get("label",""))[:30],
                                AppKit.NSMakeRect(rect[0][0],rect[0][1],rect[1][0],rect[1][1]),18)
            (AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.85,.1,1) if active else
             AppKit.NSColor.colorWithRed_green_blue_alpha_(.2,.9,1,.9)).setStroke()
            box=AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AppKit.NSInsetRect(rect,-4,-4),10,10)
            box.setLineWidth_(7 if active else 3); box.stroke()
        _label("HARD BLINK TO CHOOSE   ·   WINK TO CANCEL",(40,height-60),26)


class CalibrationView(AppKit.NSView):
    controller = objc.ivar()

    def initWithController_(self, controller):
        self = objc.super(CalibrationView, self).initWithFrame_(AppKit.NSScreen.mainScreen().frame())
        if self is not None: self.controller = controller
        return self

    def drawRect_(self, _rect):
        c = self.controller
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.025,.035,.055,1).setFill()
        AppKit.NSBezierPath.fillRect_(self.bounds())
        bounds = self.bounds()
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.72,.10,.12,1).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((24,bounds.size.height/2-24),(150,48)),10,10).fill()   # mid-left: corners hold dots
        _label("EXIT (Esc×3)",(38,bounds.size.height/2-9))
        _label(c.cal_message,(bounds.size.width/2-420,bounds.size.height-70),26)

        # Live camera view, so users can see whether their face is found.
        panel = ((bounds.size.width-300, 35), (260, 190))
        AppKit.NSColor.colorWithWhite_alpha_(.08,.92).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(panel,14,14).fill()
        live = time.monotonic()-c.latest_seen < .7
        _label("FACE DETECTED" if live else "LOOKING FOR FACE…",(bounds.size.width-280,190),15,
               AppKit.NSColor.colorWithRed_green_blue_alpha_(.25,1,.55,1) if live
               else AppKit.NSColor.orangeColor())
        box=((bounds.size.width-275,55),(210,120))
        if c.latest_frame:
            frame_data=NSData.dataWithBytes_length_(c.latest_frame,len(c.latest_frame))
            image=AppKit.NSImage.alloc().initWithData_(frame_data)
            if image is not None: image.drawInRect_(box)
        AppKit.NSColor.colorWithWhite_alpha_(.65,1).setStroke()
        AppKit.NSBezierPath.bezierPathWithRect_(box).stroke()

        if c.cal_picker:
            # Demo start-up choice, operated with the ordinary mouse.
            for key,label,rect in _picker_buttons(bounds,c.cal_saved_label):
                enabled=key!="saved" or c.cal_saved_label is not None
                AppKit.NSColor.colorWithRed_green_blue_alpha_(
                    *((.16,.45,.95,1) if key=="new" else (.2,.7,.4,1) if enabled
                      else (.3,.3,.33,1))).setFill()
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect,18,18).fill()
                _centered_label(label,AppKit.NSMakeRect(*rect[0],*rect[1]),26)

        if c.cal_target is not None:
            x, y = c.cal_target
            point = (x*bounds.size.width, (1-y)*bounds.size.height)
            (AppKit.NSColor.colorWithRed_green_blue_alpha_(.25,1,.55,1) if c.cal_capturing
             else AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.15,1)).setFill()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(((point[0]-26,point[1]-26),(52,52))).fill()
            AppKit.NSColor.blackColor().setFill()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(((point[0]-5,point[1]-5),(10,10))).fill()

    def mouseDown_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        bounds = self.bounds()
        if self.controller.cal_picker:
            for key,_label,rect in _picker_buttons(bounds,self.controller.cal_saved_label):
                if AppKit.NSPointInRect(point,rect):
                    self.controller.picker_chose(key); return
        if point.x <= 190 and abs(point.y-bounds.size.height/2) <= 40:
            self.controller.quit_(None)


def _picker_buttons(bounds, saved_label):
    """(key, label, rect) for the start-up picker, centred on the screen."""
    w,h=520,120
    cx=bounds.size.width/2; cy=bounds.size.height/2
    saved=("Use saved calibration\n"+saved_label) if saved_label else "No saved calibration"
    return [("new","Start new calibration",((cx-w-20,cy-h/2),(w,h))),
            ("saved",saved,((cx+20,cy-h/2),(w,h)))]


class DebugView(AppKit.NSView):
    """Always-on face cam plus live tracking numbers, bottom-left."""
    controller=objc.ivar()

    def initWithController_frame_(self,controller,frame):
        self=objc.super(DebugView,self).initWithFrame_(frame)
        if self is not None: self.controller=controller
        return self

    def hitTest_(self,_point):
        return None

    def drawRect_(self,_rect):
        c=self.controller
        bounds=self.bounds()
        AppKit.NSColor.colorWithWhite_alpha_(.05,.85).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds,14,14).fill()
        box=((10,bounds.size.height-190),(320,180))
        if c.latest_frame:
            data=NSData.dataWithBytes_length_(c.latest_frame,len(c.latest_frame))
            image=AppKit.NSImage.alloc().initWithData_(data)
            if image is not None: image.drawInRect_(box)
        now=time.monotonic()
        live=now-c.latest_seen<.7
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            *((.25,1,.55,1) if live else (1,.5,.1,1))).setStroke()
        frame=AppKit.NSBezierPath.bezierPathWithRect_(box); frame.setLineWidth_(3); frame.stroke()
        sample=c.latest_sample; obs=c.latest_obs
        lines=[f"face {'yes' if live else 'NO'} · pointer {'eyes' if c.eye_pointer else 'mouse'}"
               f" · AX {'ok' if c.ax_trusted else 'NOT GRANTED'}",
               c.camera_status if not c.camera_live() else f"{c.camera_status} · "
               +(c.debug_rates or "measuring…")]
        if sample is not None and sample.valid:
            lines.append(f"gaze ({sample.x:.0f}, {sample.y:.0f})"+("  DRIFT" if sample.drift else ""))
        elif sample is not None:
            lines.append(f"gaze invalid: {sample.reason}")
        if obs is not None:
            left,right=((obs.right_blink,obs.left_blink) if c.swap_eyes
                        else (obs.left_blink,obs.right_blink))
            lines.append(f"eyes closed L {left:.2f}  R {right:.2f}  squint {obs.squint:.2f}")
        if c.gestures.last_closure:
            d,both,diff,_s,g=c.gestures.last_closure
            lines.append(f"last closure {d:.2f}s both {both:.0%} L-R {diff:+.2f} → {g or 'none'}")
        if c.last_gesture and now-c.last_gesture[1]<3:
            lines.append(f"gesture: {c.last_gesture[0].upper()}")
        p=quartz_cursor()
        near=candidates(c.accessibility_targets,p.x,p.y)
        lines.append(f"targets {len(c.accessibility_targets)} · in R={SNAP_RADIUS:.0f}: {len(near)}")
        y=bounds.size.height-212
        for line in lines:
            _label(line,(12,y),13,bold=False); y-=19


def _overlay_window(frame, level, ignores_mouse=True):
    window=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame,AppKit.NSWindowStyleMaskBorderless,AppKit.NSBackingStoreBuffered,False)
    window.setLevel_(level)
    window.setOpaque_(False); window.setBackgroundColor_(AppKit.NSColor.clearColor())
    window.setHasShadow_(False); window.setIgnoresMouseEvents_(ignores_mouse)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces|
        AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary|
        AppKit.NSWindowCollectionBehaviorStationary)
    return window


class NativeController(NSObject):
    def init(self):
        self = objc.super(NativeController, self).init()
        if self is None: return None
        self.running=True; self.control_enabled=True; self.paused=False
        self.latest_seen=0.0; self.latest_frame=None; self.latest_obs=None
        self.latest_sample=None; self.applied_sample=None
        self.engine=None; self.eye_pointer=True; self.gaze_drift=False
        self.gestures=GestureDetector(); self.gesture_queue=collections.deque()
        self.eyes_closing=False; self.swap_eyes=SWAP_EYES
        self.debug_rates=""; self.last_gesture=None
        import ApplicationServices
        # Asking with the prompt option makes macOS show its own "grant
        # Accessibility" dialog. Until granted, every posted pointer move and
        # click is silently dropped.
        self.ax_trusted=bool(ApplicationServices.AXIsProcessTrustedWithOptions(
            {ApplicationServices.kAXTrustedCheckOptionPrompt: True}))
        print(f"[OpenGaze] accessibility trusted: {self.ax_trusted}",flush=True)
        # The zoom view screenshots the screen, which needs Screen Recording.
        self.screen_capture_ok=bool(Quartz.CGPreflightScreenCaptureAccess())
        if not self.screen_capture_ok:
            Quartz.CGRequestScreenCaptureAccess()
        print(f"[OpenGaze] screen recording allowed: {self.screen_capture_ok}",flush=True)
        self.ax_timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0,self,"checkAccessibility:",None,True)
        self.calibrating=False; self.cal_steps=[]; self.cal_index=0
        self.cal_target=None; self.cal_capturing=False; self.cal_retry=False
        self.cal_message=""; self.wink_scores=None; self.cal_summary=""
        self.click_flash_until=0.0; self.click_marks=[]; self.drag_mode=False
        self.camera_status="camera not started"; self.latest_frame_at=0.0
        self.cal_picker=False; self.cal_saved_label=None; self.last_drag_point=None
        self.selected_target=None; self.selected_at=0.0; self.zoom=None
        self.keyboard_window=None; self.keyboard_display=None
        self.keyboard_title=None; self.suggestion_row_y=0.0
        self.keyboard_text=""; self.keyboard_target=None
        self.keyboard_glass=None; self.suggestion_buttons=[]
        self.exit_strip=None; self.exit_strip_height=0; self.exit_hover=False
        self.decoding=False
        self.swipe_decoder=SwipeDecoder(SWIPE_WORDS)
        self.swipe=SwipeSession(self.swipe_decoder)
        self.autocomplete=Autocomplete(SWIPE_WORDS,CORPUS_FILE,PROFILE_FILE)
        self.swipe_recording=False; self.swipe_path=[]; self.key_centers={}
        self.swipe_trace_view=None
        self.scroll_hover_direction=0; self.scroll_active_direction=0
        self.scroll_hover_since=0.0; self.scroll_dwell_progress=0.0
        self.accessibility_targets=[]; self.target_boxes_enabled=True
        self.target_scan_running=False
        self.crosshair_view=CrosshairView.alloc().initWithController_(self)
        self.crosshair_window=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0,0),(52,52)),AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,False)
        self.crosshair_window.setOpaque_(False)
        self.crosshair_window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.crosshair_window.setHasShadow_(False); self.crosshair_window.setIgnoresMouseEvents_(True)
        self.crosshair_window.setLevel_(AppKit.NSScreenSaverWindowLevel)
        self.crosshair_window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
            AppKit.NSWindowCollectionBehaviorStationary)
        self.glass=AppKit.NSVisualEffectView.alloc().initWithFrame_(((0,0),(52,52)))
        self.glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        self.glass.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        self.glass.setState_(AppKit.NSVisualEffectStateActive)
        self.glass.setWantsLayer_(True); self.glass.layer().setCornerRadius_(16)
        self.glass.addSubview_(self.crosshair_view)
        self.crosshair_window.setContentView_(self.glass)
        self.crosshair_window.orderFrontRegardless()
        self.build_target_overlay()
        self.build_zoom_window()
        self.build_calibration_window()
        self.build_safety_controls()
        self.build_scroll_controls()
        self.build_debug_window()
        self.crosshair_timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1/60,self,"updateCrosshair:",None,True)
        # A menu-bar control keeps the app out of the way while providing a
        # visible, mouse-accessible exit in addition to the Escape panic key.
        self.status_item=AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        self.status_item.button().setTitle_("◉ OpenGaze")
        self.menu=AppKit.NSMenu.alloc().init()
        mode=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Look to move · hard blink to select · wink left/right to click",None,"")
        self.menu.addItem_(mode); self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.pause_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Pause Eye Control","togglePause:","p")
        self.pause_item.setTarget_(self); self.menu.addItem_(self.pause_item)
        for title,action,key in (("Recalibrate","startCalibration:","c"),
                                 ("Eye Pointer Off","toggleEyePointer:","e")):
            item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title,action,key)
            item.setTarget_(self); self.menu.addItem_(item)
            if action=="toggleEyePointer:": self.eye_pointer_item=item
        self.target_boxes_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Hide Target Boxes","toggleTargetBoxes:","b")
        self.target_boxes_item.setTarget_(self); self.menu.addItem_(self.target_boxes_item)
        # Every gesture keeps a non-gesture equivalent. Blink detection can be
        # unreliable under bad lighting, and a click that only exists as an
        # eye gesture would simply be unavailable when that happens.
        right_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Right Click at Pointer","rightClick:","r")
        right_item.setTarget_(self); self.menu.addItem_(right_item)
        drag_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Start / End Drag at Pointer","toggleDrag:","d")
        drag_item.setTarget_(self); self.menu.addItem_(drag_item)
        hide_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Close Keyboard","hideKeyboard:","k")
        hide_item.setTarget_(self); self.menu.addItem_(hide_item)
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        emergency_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Emergency Stop","emergencyStop:","")
        emergency_item.setTarget_(self); self.menu.addItem_(emergency_item)
        quit_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit OpenGaze","quit:","q")
        quit_item.setTarget_(self); self.menu.addItem_(quit_item)
        self.status_item.setMenu_(self.menu)
        # A single Escape closes the keyboard from anywhere. The panel is
        # non-activating and deliberately never takes key focus, so it cannot
        # receive the keystroke itself - this has to be a global monitor.
        self.escape_monitor=AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown,self.on_global_key)
        threading.Thread(target=self.panic_loop,daemon=True).start()
        self.request_camera_access()
        self.target_scan_timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.75,self,"requestTargetScan:",None,True)
        self.target_scan_again=False
        AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self,"appActivated:",AppKit.NSWorkspaceDidActivateApplicationNotification,None)
        self.requestTargetScan_(None)
        return self

    # ------------------------------------------------------------ windows

    @objc.python_method
    def build_safety_controls(self):
        """Keep pause, recalibrate and stop reachable without a menu or keyboard."""
        screen=AppKit.NSScreen.mainScreen().visibleFrame()
        width,height=480,76
        origin=(screen.origin.x+screen.size.width-width-18,
                screen.origin.y+screen.size.height-height-18)
        panel=AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            (origin,(width,height)),
            AppKit.NSWindowStyleMaskBorderless|AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,False)
        panel.setLevel_(AppKit.NSScreenSaverWindowLevel)
        panel.setFloatingPanel_(True); panel.setHidesOnDeactivate_(False)
        panel.setOpaque_(False); panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces|
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary|
            AppKit.NSWindowCollectionBehaviorStationary)
        glass=AppKit.NSVisualEffectView.alloc().initWithFrame_(((0,0),(width,height)))
        glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(AppKit.NSVisualEffectStateActive)
        glass.setWantsLayer_(True); glass.layer().setCornerRadius_(18)
        self.pause_safety_key=SafetyKeyView.alloc().initWithFrame_controller_title_value_accent_(
            ((8,8),(202,60)),self,"Ⅱ  PAUSE","PAUSE",False)
        recal=SafetyKeyView.alloc().initWithFrame_controller_title_value_accent_(
            ((218,8),(122,60)),self,"◎  CALIBRATE","RECALIBRATE",False)
        stop=SafetyKeyView.alloc().initWithFrame_controller_title_value_accent_(
            ((348,8),(124,60)),self,"■  STOP","EMERGENCY_STOP",False)
        for key in (self.pause_safety_key,recal,stop): glass.addSubview_(key)
        panel.setContentView_(glass); panel.orderFrontRegardless()
        self.safety_window=panel

    @objc.python_method
    def build_scroll_controls(self):
        """Install persistent up/down dwell targets at the right screen edge."""
        screen=AppKit.NSScreen.mainScreen().visibleFrame()
        width,height=98,244
        origin=(screen.origin.x+screen.size.width-width-18,
                screen.origin.y+(screen.size.height-height)/2)
        panel=AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            (origin,(width,height)),
            AppKit.NSWindowStyleMaskBorderless|AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,False)
        panel.setLevel_(AppKit.NSScreenSaverWindowLevel)
        panel.setFloatingPanel_(True); panel.setHidesOnDeactivate_(False)
        panel.setOpaque_(False); panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        # Scroll events are delivered to the window beneath the pointer. If this
        # decorative overlay accepts mouse input, it consumes every generated
        # wheel event itself and Notes/Safari never receive anything. Detection
        # is geometry-based, so the entire panel can safely be click-through.
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces|
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary|
            AppKit.NSWindowCollectionBehaviorStationary)
        glass=AppKit.NSVisualEffectView.alloc().initWithFrame_(((0,0),(width,height)))
        glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(AppKit.NSVisualEffectStateActive)
        glass.setWantsLayer_(True); glass.layer().setCornerRadius_(20)
        down=ScrollZoneView.alloc().initWithFrame_controller_direction_(
            ((6,6),(86,112)),self,-1)
        up=ScrollZoneView.alloc().initWithFrame_controller_direction_(
            ((6,126),(86,112)),self,1)
        glass.addSubview_(down); glass.addSubview_(up)
        panel.setContentView_(glass); panel.orderFrontRegardless()
        self.scroll_window=panel; self.scroll_zone_views=(up,down)
        self.scroll_timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1/30,self,"updateScroll:",None,True)

    @objc.python_method
    def build_target_overlay(self):
        screen=AppKit.NSScreen.mainScreen().frame()
        panel=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            (screen.origin,screen.size),AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,False)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False); panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(False); panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces|
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary|
            AppKit.NSWindowCollectionBehaviorStationary)
        self.target_overlay_screen=screen
        self.target_overlay_view=TargetOverlayView.alloc().initWithController_frame_(
            self,((0,0),screen.size))
        panel.setContentView_(self.target_overlay_view); panel.orderFrontRegardless()
        self.target_overlay_window=panel

    @objc.python_method
    def build_zoom_window(self):
        screen=AppKit.NSScreen.mainScreen().frame()
        self.zoom_window=_overlay_window((screen.origin,screen.size),AppKit.NSStatusWindowLevel)
        self.zoom_view=ZoomView.alloc().initWithController_frame_(self,((0,0),screen.size))
        self.zoom_window.setContentView_(self.zoom_view)

    @objc.python_method
    def build_debug_window(self):
        screen=AppKit.NSScreen.mainScreen().visibleFrame()
        frame=((screen.origin.x+18,screen.origin.y+18),(340,310))
        # Above the calibration screen and keyboard, so it is always visible.
        self.debug_window=_overlay_window(frame,AppKit.NSScreenSaverWindowLevel)
        self.debug_view=DebugView.alloc().initWithController_frame_(self,((0,0),frame[1]))
        self.debug_window.setContentView_(self.debug_view)
        self.debug_window.orderFrontRegardless()

    @objc.python_method
    def build_calibration_window(self):
        screen=AppKit.NSScreen.mainScreen().frame()
        self.cal_window=_overlay_window((screen.origin,screen.size),
                                        AppKit.NSScreenSaverWindowLevel-1,False)
        self.cal_window.setOpaque_(True)
        self.cal_view=CalibrationView.alloc().initWithController_(self)
        self.cal_window.setContentView_(self.cal_view)

    def checkAccessibility_(self,_timer):
        import ApplicationServices
        trusted=bool(ApplicationServices.AXIsProcessTrusted())
        if trusted!=self.ax_trusted:
            print(f"[OpenGaze] accessibility trusted: {trusted}",flush=True)
        self.ax_trusted=trusted

    def toggleTargetBoxes_(self,_sender):
        self.target_boxes_enabled=not self.target_boxes_enabled
        self.target_boxes_item.setTitle_(
            "Hide Target Boxes" if self.target_boxes_enabled else "Show Target Boxes")
        self.target_overlay_view.setNeedsDisplay_(True)

    def toggleEyePointer_(self,_sender):
        self.eye_pointer=not self.eye_pointer
        self.eye_pointer_item.setTitle_("Eye Pointer Off" if self.eye_pointer else "Eye Pointer On")

    def deferredTargetScan_(self,_sender):
        self.target_scan_deferred=False
        self.requestTargetScan_(None)

    def appActivated_(self,_note):
        # Switching apps must refresh the boxes now, not on the next tick.
        self.requestTargetScan_(None)

    def requestTargetScan_(self,_sender):
        # Scans run even with the boxes hidden: snapping needs the targets.
        if not self.running: return
        if self.target_scan_running:
            self.target_scan_again=True   # run once more when this one ends
            return
        # Scans cost the scanned app CPU; never run them back to back.
        wait=1.0-(time.monotonic()-getattr(self,"last_scan_at",0.0))
        if wait>0:
            if not getattr(self,"target_scan_deferred",False):
                self.target_scan_deferred=True
                self.performSelector_withObject_afterDelay_("deferredTargetScan:",None,wait)
            return
        self.last_scan_at=time.monotonic()
        self.target_scan_again=False
        self.target_scan_running=True
        def scan():
            started=time.monotonic()
            try: targets=discover_targets(os.getpid())
            except Exception: targets=[]
            self.last_scan_seconds=time.monotonic()-started
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyTargets:",targets,False)
        threading.Thread(target=scan,daemon=True).start()

    def applyTargets_(self,targets):
        print(f"[OpenGaze] targets: {len(targets or [])} "
              f"(scan {getattr(self,'last_scan_seconds',0)*1000:.0f} ms)",flush=True)
        try:   # debug dump: the shell is not Accessibility-trusted, this app is
            Path("/private/tmp/opengaze-targets.json").write_text(json.dumps(
                [{k:v for k,v in dict(t).items() if isinstance(v,(str,int,float))}
                 for t in (targets or [])],indent=0))
        except Exception:
            pass
        self.accessibility_targets=[dict(t) for t in (targets or [])]
        self.target_scan_running=False
        if self.target_scan_again: self.requestTargetScan_(None)
        self.target_overlay_view.setNeedsDisplay_(True)

    # ------------------------------------------------------------ scrolling

    @objc.python_method
    def scroll_direction_at_pointer(self):
        if getattr(self,"scroll_window",None) is None:
            return 0
        point=AppKit.NSEvent.mouseLocation()
        if not AppKit.NSPointInRect(point,self.scroll_window.frame()):
            return 0
        local=self.scroll_window.convertPointFromScreen_(point)
        if 126 <= local.y <= 238: return 1
        if 6 <= local.y <= 118: return -1
        return 0

    @objc.python_method
    def reset_scroll_state(self):
        changed=bool(self.scroll_hover_direction or self.scroll_active_direction)
        self.scroll_hover_direction=0; self.scroll_active_direction=0
        self.scroll_hover_since=0.0; self.scroll_dwell_progress=0.0
        if changed:
            for view in getattr(self,"scroll_zone_views",()):
                view.setNeedsDisplay_(True)

    def updateScroll_(self,_timer):
        if (not self.running or self.paused or not self.control_enabled or
                self.keyboard_visible() or self.drag_mode or self.swipe_recording
                or self.zoom is not None or self.calibrating):
            self.reset_scroll_state(); return
        direction=self.scroll_direction_at_pointer()
        if not direction:
            self.reset_scroll_state(); return
        now=time.monotonic()
        if direction!=self.scroll_hover_direction:
            self.scroll_hover_direction=direction; self.scroll_active_direction=0
            self.scroll_hover_since=now; self.scroll_dwell_progress=0.0
        elapsed=now-self.scroll_hover_since
        self.scroll_dwell_progress=min(1.0,elapsed/SCROLL_DWELL_SECONDS)
        if elapsed>=SCROLL_DWELL_SECONDS:
            self.scroll_active_direction=direction
            # Start gently, then ramp for long documents without becoming
            # uncontrollable. Leaving the zone stops on the very next tick.
            speed=int(min(42,10+(elapsed-SCROLL_DWELL_SECONDS)*16))
            event=Quartz.CGEventCreateScrollWheelEvent(
                EVENT_SOURCE,Quartz.kCGScrollEventUnitPixel,1,direction*speed)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap,event)
        for view in self.scroll_zone_views: view.setNeedsDisplay_(True)

    # ------------------------------------------------------------ safety

    @objc.python_method
    def pointer_over_safety_controls(self):
        return (getattr(self,"safety_window",None) is not None and
                AppKit.NSPointInRect(
                    AppKit.NSEvent.mouseLocation(),self.safety_window.frame()))

    def togglePause_(self,_sender):
        self.set_paused(not self.paused)

    @objc.python_method
    def set_paused(self,paused):
        self.paused=bool(paused)
        self.control_enabled=not self.paused
        self.pending_blink=False; self.gesture_queue.clear()
        self.swipe_recording=False; self.swipe_path=[]
        self.clear_selection(); self.close_zoom()
        self.reset_scroll_state()
        self.release_drag(); self.hideKeyboard_(None)
        if self.paused:
            self.status_item.button().setTitle_("Ⅱ OpenGaze · PAUSED")
            self.pause_item.setTitle_("Resume Eye Control")
            self.pause_safety_key.keyTitle="▶  RESUME"
            self.pause_safety_key.keyValue="RESUME"
        else:
            self.status_item.button().setTitle_("● OpenGaze · active")
            self.pause_item.setTitle_("Pause Eye Control")
            self.pause_safety_key.keyTitle="Ⅱ  PAUSE"
            self.pause_safety_key.keyValue="PAUSE"
        self.pause_safety_key.setNeedsDisplay_(True)
        self.crosshair_view.setNeedsDisplay_(True)

    def emergencyStop_(self,_sender):
        """Immediately neutralize input state, then terminate the controller."""
        self.gesture_queue.clear()
        self.reset_scroll_state(); self.release_drag()
        self.running=False; self.control_enabled=False
        AppKit.NSApp.terminate_(None)

    @objc.python_method
    def on_global_key(self, event):
        try:
            if event.keyCode()==53 and self.keyboard_visible():
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "hideKeyboard:",None,False)
        except Exception:
            pass

    # ------------------------------------------------------------ camera

    @objc.python_method
    def request_camera_access(self):
        status=AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeVideo)
        if status == AVFoundation.AVAuthorizationStatusAuthorized:
            self.startCamera_(None)
        elif status == AVFoundation.AVAuthorizationStatusNotDetermined:
            def decided(granted):
                selector="startCamera:" if granted else "cameraFailed:"
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    selector,None,False)
            self.camera_auth_callback=decided
            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVFoundation.AVMediaTypeVideo,decided)
        else:
            self.cameraFailed_(None)

    def startCamera_(self, _sender):
        self.status_item.button().setTitle_("◉ OpenGaze · starting camera")
        self.cal_message="Starting camera… (iPhone: keep it nearby, on a stand facing you)"
        self.cal_target=None
        self.cal_window.orderFrontRegardless(); self.cal_view.setNeedsDisplay_(True)
        threading.Thread(target=self.camera_loop_forever,daemon=True).start()

    @objc.python_method
    def camera_loop_forever(self):
        # A bug in per-frame code must never silently end eye tracking: log
        # it and restart the loop (the calibrated engine is kept).
        import traceback
        while self.running:
            try:
                self.camera_loop(); return
            except Exception:
                print("[OpenGaze] camera loop crashed, restarting:\n"+traceback.format_exc(),flush=True)
                time.sleep(.5)

    def cameraFailed_(self, _sender):
        self.status_item.button().setTitle_("⚠ OpenGaze · camera blocked")
        self.cal_message=("Camera unavailable. Enable OpenGaze or Terminal in System Settings → "
                          "Privacy & Security → Camera, then relaunch.")
        self.cal_target=None
        self.cal_window.orderFrontRegardless(); self.cal_view.setNeedsDisplay_(True)
        self.performSelector_withObject_afterDelay_("closeCalibration:",None,6.0)

    @objc.python_method
    def camera_loop(self):
        try:
            from gaze_engine import GazeEngine
            width,height=screen_size()
            if self.engine is None:      # a restarted loop keeps its calibration
                self.engine=GazeEngine(width,height)
        except Exception as error:
            print(f"[OpenGaze] gaze engine failed: {error}",flush=True)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "cameraFailed:", None, False)
            return
        announced=False; count=0; stats={}; stats_at=time.monotonic(); logged_closures=0
        cap=None; failures=0; last_frame=time.monotonic()
        while self.running:
            if cap is None:
                # The iPhone (Continuity) camera can vanish at any time; keep
                # reconnecting, and fall back to the built-in one if it stays gone.
                index,name=camera_choice() if failures<3 else (0,"built-in camera (fallback)")
                self.set_camera_status(f"starting camera {index}: {name}…")
                cap=cv2.VideoCapture(index)
                if not cap.isOpened():
                    cap.release(); cap=None; failures+=1
                    self.set_camera_status(f"camera {name} unavailable, retrying…")
                    time.sleep(1); continue
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
                last_frame=time.monotonic(); camera_name=f"{index}: {name}"
            ok,frame=cap.read()
            if not ok:
                if time.monotonic()-last_frame>3:
                    cap.release(); cap=None; failures+=1
                    self.set_camera_status(f"camera {camera_name} stopped sending frames, reconnecting…")
                else:
                    time.sleep(.01)
                continue
            now=time.monotonic(); count+=1
            if now-last_frame>1 or self.latest_frame_at==0:
                self.set_camera_status(f"camera {camera_name} on")
            last_frame=now; self.latest_frame_at=now; failures=0
            try:
                sample,obs=self.engine.process(frame,now)
            except Exception as error:
                print(f"[OpenGaze] gaze inference failed: {error}",flush=True)
                continue
            if count%3==0:
                # Mirrored preview, so moving left moves the image left.
                small=cv2.flip(cv2.resize(frame,(320,180)),1)
                good,encoded=cv2.imencode(".jpg",small,[cv2.IMWRITE_JPEG_QUALITY,70])
                if good: self.latest_frame=encoded.tobytes()
            if obs is not None:
                self.latest_seen=now; self.latest_obs=obs
                if not announced:
                    announced=True
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "cameraReady:",None,False)
                left,right=((obs.right_blink,obs.left_blink) if self.swap_eyes
                            else (obs.left_blink,obs.right_blink))
                gesture=self.gestures.feed(now,left,right,obs.squint)
            else:
                gesture=self.gestures.feed(now,None,None)
            self.eyes_closing=self.gestures.closing
            self.latest_sample=sample
            # Every ~5s: how many samples were usable, and why not.
            stats[sample.reason or "valid"]=stats.get(sample.reason or "valid",0)+1
            if now-stats_at>5:
                where=f" last=({sample.x:.0f},{sample.y:.0f})" if sample.valid else ""
                print(f"[OpenGaze] gaze {dict(stats)}{where}",flush=True)
                total=sum(stats.values()) or 1
                self.debug_rates=(f"{total/(now-stats_at):.0f} fps · "+
                                  " ".join(f"{k} {100*v//total}%" for k,v in stats.items()))
                stats.clear(); stats_at=now
            closure=self.gestures.last_closure
            if self.gestures.closures!=logged_closures and closure is not None:
                logged_closures=self.gestures.closures
                d,both,diff,squint,g=closure
                print(f"[OpenGaze] closure {d:.2f}s both={both:.0%} L-R={diff:+.2f} "
                      f"squint={squint:.2f} -> {g or 'none'}",flush=True)
            if gesture: self.last_gesture=(gesture,now)
            if gesture and not self.calibrating:
                self.gesture_queue.append((gesture,now))
        if cap is not None: cap.release()

    @objc.python_method
    def set_camera_status(self, status):
        if status==self.camera_status: return
        self.camera_status=status
        print(f"[OpenGaze] {status}",flush=True)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("cameraStatus:",None,False)

    def cameraStatus_(self, _sender):
        # Before the first face is seen, the calibration screen is the camera
        # prompt: it says what the camera is doing and shows the live image.
        if (not self.calibrating and not self.cal_picker and self.engine is not None
                and not self.engine.calibrated):
            self.cal_message=self.camera_status.capitalize()
            self.cal_view.setNeedsDisplay_(True)

    @objc.python_method
    def camera_live(self):
        return time.monotonic()-self.latest_frame_at<1.0

    def cameraReady_(self, _sender):
        self.status_item.button().setTitle_("● OpenGaze · active")
        self.show_picker()

    @objc.python_method
    def show_picker(self, message="Click to choose how to start"):
        self.cal_picker=True; self.cal_target=None; self.cal_message=message
        self.cal_saved_label=None
        if CALIBRATION_FILE.exists():
            self.cal_saved_label=time.strftime(
                "saved %b %d, %H:%M",time.localtime(CALIBRATION_FILE.stat().st_mtime))
        self.cal_window.orderFrontRegardless(); self.cal_view.setNeedsDisplay_(True)

    @objc.python_method
    def picker_chose(self, key):
        if key=="new":
            self.cal_picker=False; self.startCalibration_(None)
        elif key=="saved" and self.cal_saved_label is not None:
            try:
                self.engine.load(CALIBRATION_FILE)
            except Exception as error:
                print(f"[OpenGaze] loading saved calibration failed: {error!r}",flush=True)
                self.show_picker(f"Could not use the saved calibration ({error}). Calibrate instead.")
                return
            print("[OpenGaze] loaded saved calibration",flush=True)
            self.cal_picker=False; self.cal_summary="saved calibration"
            self.finish_calibration()

    # ------------------------------------------------------------ calibration

    def startCalibration_(self,_sender):
        if self.engine is None: return
        if not self.camera_live():
            # Calibrating without frames can only fail; wait for the camera.
            self.cal_message=f"Waiting for the camera before calibrating · {self.camera_status}"
            self.cal_target=None
            self.cal_window.orderFrontRegardless(); self.cal_view.setNeedsDisplay_(True)
            self.performSelector_withObject_afterDelay_("startCalibration:",None,1.0)
            return
        self.hideKeyboard_(None); self.close_zoom(); self.clear_selection()
        self.release_drag()
        self.engine.reset()
        self.calibrating=True; self.gesture_queue.clear()
        self.cal_steps=([("calibration",p) for p in CAL_POINTS]+
                        [("validation",p) for p in VAL_POINTS])
        self.cal_index=-1; self.cal_retry=False; self.cal_capturing=False
        self.cal_window.orderFrontRegardless()
        self.nextCalibrationStep_(None)

    def nextCalibrationStep_(self,_sender):
        if not self.calibrating: return
        self.cal_index+=1
        finished=self.cal_index>=len(self.cal_steps)
        kind,point=(None,None) if finished else self.cal_steps[self.cal_index]
        if (finished or kind=="validation") and not self.engine.calibrated:
            try: self.engine.finish_calibration()
            except Exception as error:
                print(f"[OpenGaze] calibration fit failed: {error!r}",flush=True)
                self.fail_calibration(str(error)); return
        if finished:
            if VAL_POINTS:
                n,error=self.engine.finish_validation()
                self.cal_summary=(f"{round(error)} pt error" if error is not None
                                  else "bias fix only" if n else "unvalidated")
            else:
                self.cal_summary="calibrated"
            try:   # every fresh calibration becomes the saved one
                self.engine.save(CALIBRATION_FILE)
                print(f"[OpenGaze] calibration saved to {CALIBRATION_FILE}",flush=True)
            except Exception as error:
                print(f"[OpenGaze] saving calibration failed: {error!r}",flush=True)
            self.finish_calibration(); return
        total=len(CAL_POINTS) if kind=="calibration" else len(VAL_POINTS)
        index=self.cal_index if kind=="calibration" else self.cal_index-len(CAL_POINTS)
        label="Look at the dot" if kind=="calibration" else "Checking"
        self.cal_message=f"{label} · {index+1} of {total}"
        self.cal_target=point; self.cal_capturing=False
        self.performSelector_withObject_afterDelay_("beginCapture:",None,SETTLE_SECONDS)
        self.cal_view.setNeedsDisplay_(True)

    def beginCapture_(self,_sender):
        if not self.calibrating: return
        kind,(x,y)=self.cal_steps[self.cal_index]
        width,height=screen_size()
        self.engine.begin_target(kind,x*width,y*height)
        self.cal_capturing=True; self.cal_view.setNeedsDisplay_(True)
        self.performSelector_withObject_afterDelay_("endCapture:",None,CAPTURE_SECONDS)

    def endCapture_(self,_sender):
        if not self.calibrating: return
        captured=self.engine.end_target()
        if captured<4 and not self.cal_retry:
            # One more try at the same dot before moving on without it.
            self.cal_retry=True
            self.cal_message="Hold still and keep looking at the dot"
            self.cal_view.setNeedsDisplay_(True)
            self.beginCapture_(None); return
        self.cal_retry=False
        self.nextCalibrationStep_(None)

    def finishWinkTest_(self,_sender):
        scores=self.wink_scores or []; self.wink_scores=None
        # MediaPipe may name the eyes from the viewer's side. If "left" barely
        # moved while the user closed their left eye, swap the two.
        if len(scores)>=5:
            m=statistics.median(scores)
            if m<-0.15: self.swap_eyes=True
            elif m>0.15: self.swap_eyes=False
        self.nextCalibrationStep_(None)

    @objc.python_method
    def finish_calibration(self):
        import ApplicationServices
        # Without Accessibility permission macOS silently drops every posted
        # pointer and click event, which looks exactly like tracking stopped.
        trusted=bool(ApplicationServices.AXIsProcessTrusted())
        print(f"[OpenGaze] calibration done ({self.cal_summary}); "
              f"accessibility trusted: {trusted}",flush=True)
        if not trusted:
            self.cal_summary="grant Accessibility permission, then relaunch"
        self.calibrating=False; self.cal_target=None
        self.gestures.reset(); self.gesture_queue.clear()
        self.cal_window.orderOut_(None)
        self.status_item.button().setTitle_(f"● OpenGaze · {self.cal_summary}")

    @objc.python_method
    def fail_calibration(self,reason):
        self.calibrating=False; self.cal_target=None
        self.cal_message=f"Calibration failed: {reason}. Use ◎ CALIBRATE to retry."
        self.cal_view.setNeedsDisplay_(True)
        self.performSelector_withObject_afterDelay_("closeCalibration:",None,4.0)

    def closeCalibration_(self,_sender):
        if not self.calibrating: self.cal_window.orderOut_(None)

    # ------------------------------------------------------------ main tick

    @objc.python_method
    def release_drag(self):
        """Make sure we never leave the mouse button held down.

        Drag mode holds a synthetic button press across many event loop turns.
        If the process exits while that press is outstanding, the button stays
        down for the whole system and the machine is effectively unusable - and
        the person this is built for cannot reach a physical mouse to clear it.
        """
        if not getattr(self,"drag_mode",False):
            return
        self.drag_mode=False
        try:
            where=quartz_cursor()
            Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                Quartz.CGEventCreateMouseEvent(
                    EVENT_SOURCE,Quartz.kCGEventLeftMouseUp,
                    where,Quartz.kCGMouseButtonLeft))
        except Exception:
            pass

    def quit_(self, _sender):
        # Keep the release explicit here as well as in emergencyStop_; this is
        # the invariant that prevents any exit path leaving macOS mid-drag.
        self.release_drag()
        self.emergencyStop_(_sender)

    @objc.python_method
    def apply_gaze(self):
        """Move the real pointer to the newest valid gaze sample."""
        sample=self.latest_sample
        if sample is None or sample is self.applied_sample: return
        self.applied_sample=sample
        self.gaze_drift=bool(sample.valid and sample.drift)
        if self.wink_scores is not None and sample.obs is not None:
            self.wink_scores.append(sample.obs.left_blink-sample.obs.right_blink)
        if not sample.valid or not self.eye_pointer or self.calibrating: return
        # Any eye starting to close means a click is probably coming: hold
        # the pointer still so the wink lands where the user was looking.
        if (sample.obs is not None and
                max(sample.obs.left_blink,sample.obs.right_blink)>FREEZE_CLOSURE): return
        if self.drag_mode: self.last_drag_point=(sample.x,sample.y)
        move_pointer(sample.x,sample.y,self.drag_mode)

    def updateCrosshair_(self, _timer):
        self.apply_gaze()
        while self.gesture_queue:
            gesture,at=self.gesture_queue.popleft()
            self.handle_gesture(gesture,at)
        point=AppKit.NSEvent.mouseLocation()
        self.crosshair_window.setFrameOrigin_((point.x-26,point.y-26))
        if self.keyboard_visible():
            self.track_keyboard_pointer()
        elif self.drag_mode:
            # Quartz space, never the Cocoa point used for the reticle above.
            where=quartz_cursor()
            moved=(self.last_drag_point is None
                   or abs(where.x-self.last_drag_point[0])>0.5
                   or abs(where.y-self.last_drag_point[1])>0.5)
            if moved:
                self.last_drag_point=(where.x,where.y)
                drag=Quartz.CGEventCreateMouseEvent(
                    EVENT_SOURCE,Quartz.kCGEventLeftMouseDragged,
                    where,Quartz.kCGMouseButtonLeft)
                Quartz.CGEventSetIntegerValueField(
                    drag,Quartz.kCGMouseEventButtonNumber,Quartz.kCGMouseButtonLeft)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap,drag)
        if self.zoom is not None:
            self.zoom_view.setNeedsDisplay_(True)
        if (self.selected_target is not None and
                time.monotonic()-self.selected_at>SELECTION_TIMEOUT):
            self.clear_selection()
        if self.calibrating and self.cal_index>=0:
            self.cal_view.setNeedsDisplay_(True)
        self.debug_view.setNeedsDisplay_(True)
        self.target_overlay_view.setNeedsDisplay_(True)
        self.crosshair_view.setNeedsDisplay_(True)

    def flashCrosshair_(self, _sender):
        self.click_flash_until=time.monotonic()+.22
        self.crosshair_view.setNeedsDisplay_(True)

    # ------------------------------------------------------------ gestures

    @objc.python_method
    def handle_gesture(self, gesture, at):
        if self.calibrating or not self.running: return
        # Before any calibration (start-up picker) gestures would act on
        # wherever the mouse happens to be; the picker is mouse-only.
        if self.cal_picker or self.engine is None or not self.engine.calibrated: return
        if self.paused:
            # While paused, a left wink may operate only the persistent safety
            # strip. Everything else is inert.
            if gesture=="wink_left" and self.pointer_over_safety_controls():
                self.leftClick_(None)
            return
        if self.zoom is not None:
            if gesture=="hard_blink": self.choose_zoomed()
            elif gesture in ("wink_left","wink_right"): self.close_zoom()
            return
        if self.keyboard_visible():
            if gesture=="blink" and self.pointer_over_keyboard():
                self.swipe_boundary(at)
            elif gesture=="wink_left":
                self.leftClick_(None)
            return
        if gesture=="hard_blink":
            self.select_near_gaze()
        elif gesture in ("wink_left","wink_right"):
            target=self.selected_target
            if target is not None:
                self.clear_selection()
                move_pointer(*center(target))
            if gesture=="wink_left": self.leftClick_(None)
            else: self.rightClick_(None)

    @objc.python_method
    def select_near_gaze(self):
        where=quartz_cursor()
        near=candidates(self.accessibility_targets,where.x,where.y)
        print(f"[OpenGaze] hard blink at ({where.x:.0f},{where.y:.0f}): "
              f"{len(near)} of {len(self.accessibility_targets)} targets in range -> "
              f"{'nothing' if not near else 'select '+str(near[0].get('label',''))[:30] if len(near)==1 else 'zoom'}",
              flush=True)
        if not near:
            self.clear_selection(); return
        if len(near)==1:
            self.set_selected(near[0]); return
        self.open_zoom(near)

    @objc.python_method
    def set_selected(self, target):
        self.selected_target=target; self.selected_at=time.monotonic()
        self.target_overlay_view.setNeedsDisplay_(True)
        self.status_item.button().setTitle_(
            f"◎ {str(target.get('label',''))[:24]} · wink to click")

    @objc.python_method
    def clear_selection(self):
        if self.selected_target is None: return
        self.selected_target=None
        self.target_overlay_view.setNeedsDisplay_(True)
        self.status_item.button().setTitle_("● OpenGaze · active")

    @objc.python_method
    def open_zoom(self, targets):
        width,height=screen_size()
        region=zoom_region(targets,width,height)
        dest=zoom_dest(region,width,height)
        # Labelled tiles immediately; the screenshot replaces them when the
        # asynchronous capture lands (CGWindowListCreateImage is obsolete and
        # returns a black image on current macOS).
        self.zoom={"region":region,"dest":dest,"originals":targets,"image":None,
                   "targets":[to_zoom(t,region,dest) for t in targets]}
        self.zoom_window.orderFrontRegardless(); self.zoom_view.setNeedsDisplay_(True)
        self.capture_zoom(self.zoom)

    @objc.python_method
    def capture_zoom(self, zoom):
        """Screenshot the zoom region with ScreenCaptureKit, leaving out our
        own overlays (boxes, ring, zoom, debug panel)."""
        import ScreenCaptureKit as SCK
        x,y,w,h=zoom["region"]
        def got_image(image,error):
            if image is None:
                print(f"[OpenGaze] zoom capture failed: {error}",flush=True); return
            zoom["image"]=AppKit.NSImage.alloc().initWithCGImage_size_(image,(w,h))
            self.zoom_view.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setNeedsDisplay:",True,False)
        def got_content(content,error):
            if content is None:
                print(f"[OpenGaze] zoom capture unavailable (Screen Recording?): {error}",flush=True)
                return
            main=Quartz.CGMainDisplayID()
            display=next((d for d in content.displays() if d.displayID()==main),None)
            if display is None: return
            ours=[win for win in content.windows()
                  if win.owningApplication() is not None
                  and win.owningApplication().processID()==os.getpid()]
            content_filter=SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display,ours)
            config=SCK.SCStreamConfiguration.alloc().init()
            scale=AppKit.NSScreen.mainScreen().backingScaleFactor()
            config.setSourceRect_(Quartz.CGRectMake(x,y,w,h))
            config.setWidth_(int(w*scale)); config.setHeight_(int(h*scale))
            config.setShowsCursor_(False)
            SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
                content_filter,config,got_image)
        try:
            SCK.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                False,True,got_content)
        except Exception as error:
            print(f"[OpenGaze] zoom capture error: {error!r}",flush=True)

    @objc.python_method
    def choose_zoomed(self):
        where=quartz_cursor()
        chosen=pick(self.zoom["targets"],where.x,where.y)
        original=self.zoom["originals"][self.zoom["targets"].index(chosen)]
        self.close_zoom(); self.set_selected(original)

    @objc.python_method
    def close_zoom(self):
        if self.zoom is None: return
        self.zoom=None; self.zoom_window.orderOut_(None)

    # ------------------------------------------------------------ clicking

    def leftClick_(self, _sender):
        on_safety=self.pointer_over_safety_controls()
        if self.paused and not on_safety: return
        if self.scroll_direction_at_pointer(): return
        where=quartz_cursor()
        print(f"[OpenGaze] left click at ({where.x:.0f},{where.y:.0f})",flush=True)
        self.flashCrosshair_(None)
        here=quartz_cursor(); self.click_marks.append(("L",here.x,here.y,time.monotonic()))
        self.performSelector_withObject_afterDelay_("requestTargetScan:",None,.4)
        on_keyboard=self.pointer_over_keyboard()
        target=click(show_keyboard=False)
        if on_safety:
            return          # a safety action must never reopen the keyboard
        if on_keyboard:
            return          # the panel's own key handling deals with this click
        if target and int(target["pid"]) != os.getpid(): self.show_keyboard(target)

    def rightClick_(self, _sender):
        if self.pointer_over_keyboard():
            return          # our own keys have no context menu
        if self.drag_mode:
            return          # a right click mid-drag would only confuse the target
        self.flashCrosshair_(None)
        where=quartz_cursor()
        self.click_marks.append(("R",where.x,where.y,time.monotonic()))
        self.performSelector_withObject_afterDelay_("requestTargetScan:",None,.4)
        # kCGEventRightMouseDown / kCGEventRightMouseUp with kCGMouseButtonRight,
        # click count 1 and a short hold: see bridge.post_click.
        post_click(where,Quartz.kCGEventRightMouseDown,Quartz.kCGEventRightMouseUp,
                   Quartz.kCGMouseButtonRight)

    def toggleDrag_(self, _sender):
        point=quartz_cursor()
        self.last_drag_point=(point.x,point.y)
        if self.drag_mode:
            kind=Quartz.kCGEventLeftMouseUp; self.drag_mode=False
            self.status_item.button().setTitle_("● OpenGaze · active")
        else:
            kind=Quartz.kCGEventLeftMouseDown; self.drag_mode=True
            self.status_item.button().setTitle_("◆ DRAG MODE · menu to release")
        event=Quartz.CGEventCreateMouseEvent(
            EVENT_SOURCE,kind,point,Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,event)
        self.crosshair_view.setNeedsDisplay_(True)

    # ------------------------------------------------------------ keyboard

    @objc.python_method
    def pointer_over_keyboard(self):
        """True when the pointer sits inside the visible keyboard panel.

        The panel is deliberately non-activating so that the app being typed
        into keeps keyboard focus. A side effect is that pressing one of our own
        keys leaves that other app frontmost, so the focus probe still reports
        it - which makes "the user pressed a key" indistinguishable from "the
        user clicked a new text field" by focus alone. Geometry can tell them
        apart, and getting this wrong re-opened the keyboard on every keystroke
        and wiped the text buffer each time.
        """
        if not self.keyboard_visible():
            return False
        # Cocoa coordinates on both sides: NSEvent.mouseLocation and NSWindow.frame.
        return AppKit.NSPointInRect(
            AppKit.NSEvent.mouseLocation(), self.keyboard_window.frame())

    @objc.python_method
    def panel_point(self):
        """Pointer position in keyboard-panel coordinates.

        The swipe path must be recorded in the same space as the key centres it
        is matched against; screen coordinates only line up with them by
        coincidence when the panel sits at the screen origin.
        """
        point=AppKit.NSEvent.mouseLocation()
        if self.keyboard_window is None: return (point.x,point.y)
        local=self.keyboard_window.convertPointFromScreen_(point)
        return (local.x,local.y)

    @objc.python_method
    def track_keyboard_pointer(self):
        """Feed the swipe session and watch the finish strip, every tick."""
        local=self.panel_point()
        in_strip=local[1]>=self.keyboard_window.frame().size.height-self.exit_strip_height
        if in_strip!=self.exit_hover:
            self.exit_hover=in_strip; self.exit_strip.setNeedsDisplay_(True)
        if in_strip:
            if self.swipe.recording: self.finish_sentence()
            return
        self.swipe.feed(local[0],local[1],time.monotonic())
        if self.swipe_recording:
            if not self.swipe_path or abs(local[0]-self.swipe_path[-1][0])>1.2 \
                    or abs(local[1]-self.swipe_path[-1][1])>1.2:
                self.swipe_path.append(local)
            if self.swipe_trace_view is not None:
                self.swipe_trace_view.setNeedsDisplay_(True)

    @objc.python_method
    def swipe_boundary(self, at):
        """A natural blink: end the current word and start the next."""
        self.swipe.boundary(at)
        self.swipe_recording=True
        self.swipe_path=[self.panel_point()]
        self.render_swipe()

    @objc.python_method
    def render_swipe(self):
        preview=" ".join(slot[0]["word"] for slot in self.swipe.slots)
        text=self.keyboard_text+preview+(" …" if self.swipe.recording else "")
        self.keyboard_display.setStringValue_(text)
        if self.swipe.slots:
            self.show_suggestions([c["word"] for c in self.swipe.slots[-1][:6]],"SLOT")
        if self.swipe_trace_view is not None:
            self.swipe_trace_view.setNeedsDisplay_(True)

    @objc.python_method
    def finish_sentence(self):
        """Close the last word and send the whole sentence to the LLM."""
        self.swipe.end()
        slots=[list(slot) for slot in self.swipe.slots]
        self.swipe.clear(); self.swipe_recording=False; self.swipe_path=[]
        self.render_swipe()
        if not slots or self.decoding: return
        self.decoding=True
        self.keyboard_title.setStringValue_("DECODING SENTENCE…")
        prior=self.keyboard_text
        def work():
            self.decoded=decode_sentence(slots,prior)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "sentenceDecoded:",None,False)
        threading.Thread(target=work,daemon=True).start()

    def sentenceDecoded_(self,_sender):
        self.decoding=False
        sentence,error=self.decoded
        if sentence: self.keyboard_text+=sentence+" "
        self.keyboard_display.setStringValue_(self.keyboard_text)
        self.keyboard_title.setStringValue_(
            f"⚠ {error} · used top words" if error else self.keyboard_hint())
        self.refresh_suggestions()

    @objc.python_method
    def flush_swipe(self):
        """Commit any undecoded words as their top candidates."""
        self.swipe.end()
        if self.swipe.slots:
            self.keyboard_text+=fallback(self.swipe.slots)+" "
        self.swipe.clear(); self.swipe_recording=False; self.swipe_path=[]

    @objc.python_method
    def refresh_suggestions(self):
        """Offer word completions for whatever has been typed so far."""
        try:
            self.show_suggestions(self.autocomplete.suggest(self.keyboard_text))
        except Exception:
            # Suggestions are a convenience; never let them break typing.
            self.show_suggestions([])

    @objc.python_method
    def show_suggestions(self, words, kind="SUGGEST"):
        for button in self.suggestion_buttons: button.removeFromSuperview()
        self.suggestion_buttons=[]
        if not words or self.keyboard_glass is None: return
        words=list(words)[:6]
        width=self.keyboard_window.frame().size.width
        gap=12; button_w=min(240,(width-60-gap*(len(words)-1))/len(words))
        total=button_w*len(words)+gap*(len(words)-1); x=(width-total)/2
        for word in words:
            button=self.make_key(word,f"{kind}:{word}",
                                 ((x,self.suggestion_row_y),(button_w,56)))
            self.keyboard_glass.addSubview_(button); self.suggestion_buttons.append(button)
            x+=button_w+gap

    @objc.python_method
    def build_keyboard(self):
        """Create the full-screen keyboard panel once and keep it.

        One panel, reused: allocating a new NSWindow per open stacked invisible
        floating windows until the keyboard stopped responding.

        It is an NSPanel with NSWindowStyleMaskNonactivatingPanel and is ordered
        in with orderFrontRegardless(), never makeKeyAndOrderFront_. That matters
        more than it looks: activating our app takes first-responder status away
        from the app the user is typing into, which is exactly the field we are
        about to insert text in.
        """
        # visibleFrame, not frame: it excludes the Dock and the menu bar, so
        # the bottom action row is never underneath the Dock.
        screen=AppKit.NSScreen.mainScreen().visibleFrame()
        width=screen.size.width; height=screen.size.height
        origin=(screen.origin.x,screen.origin.y)
        panel=AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            (origin,(width,height)),
            AppKit.NSWindowStyleMaskBorderless|AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,False)
        panel.setLevel_(AppKit.NSFloatingWindowLevel+1)
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces|
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        panel.setAppearance_(AppKit.NSAppearance.appearanceNamed_(
            AppKit.NSAppearanceNameDarkAqua))

        glass=AppKit.NSVisualEffectView.alloc().initWithFrame_(((0,0),(width,height)))
        glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(AppKit.NSVisualEffectStateActive)
        backdrop=AppKit.NSView.alloc().initWithFrame_(((0,0),(width,height)))
        backdrop.setWantsLayer_(True)
        backdrop.layer().setBackgroundColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(.04,.07,.11,.96).CGColor())
        glass.addSubview_(backdrop)
        panel.setContentView_(glass)

        self.keyboard_window=panel; self.keyboard_glass=glass

        strip=round(height*EXIT_STRIP_SHARE); self.exit_strip_height=strip
        self.exit_strip=ExitStripView.alloc().initWithController_frame_(
            self,((0,height-strip),(width,strip)))
        glass.addSubview_(self.exit_strip)
        top=height-strip

        self.keyboard_title=AppKit.NSTextField.labelWithString_("")
        self.keyboard_title.setFrame_(((30,top-40),(width-190,26)))
        self.keyboard_title.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(15,AppKit.NSFontWeightSemibold))
        self.keyboard_title.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(.45,.85,1,.95))
        glass.addSubview_(self.keyboard_title)

        # Always-present, always-reachable exit. A keyboard that covers the
        # screen with no obvious way out is worse than no keyboard.
        close=KeyView.alloc().initWithFrame_controller_title_value_accent_(
            ((width-110,top-52),(80,44)),self,"✕","CLOSE",False)
        glass.addSubview_(close)

        self.keyboard_display=AppKit.NSTextField.alloc().initWithFrame_(
            ((30,top-112),(width-60,54)))
        self.keyboard_display.setEditable_(False); self.keyboard_display.setSelectable_(False)
        self.keyboard_display.setFont_(AppKit.NSFont.systemFontOfSize_(30))
        self.keyboard_display.setBezeled_(False); self.keyboard_display.setDrawsBackground_(True)
        self.keyboard_display.setBackgroundColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(.02,.04,.07,.92))
        self.keyboard_display.setTextColor_(AppKit.NSColor.whiteColor())
        self.keyboard_display.setWantsLayer_(True)
        self.keyboard_display.layer().setCornerRadius_(10)
        glass.addSubview_(self.keyboard_display)

        self.suggestion_row_y=top-180
        rows=("QWERTYUIOP","ASDFGHJKL","ZXCVBNM")
        self.key_centers={}
        gap=10; bottom=22+64+16
        key_h=(self.suggestion_row_y-14-bottom-gap*2)/3
        key_w=min(170,(width-60-gap*9)/10)
        y=self.suggestion_row_y-14-key_h
        for row in rows:
            total=key_w*len(row)+gap*(len(row)-1); x=(width-total)/2
            for letter in row:
                glass.addSubview_(self.make_key(
                    letter,letter.lower(),((x,y),(key_w,key_h))))
                self.key_centers[letter.lower()]=(x+key_w/2,y+key_h/2)
                x+=key_w+gap
            y-=key_h+gap
        self.swipe_decoder.set_layout(self.key_centers,key_w)

        actions=(("⌫","DELETE",1.0),("SPACE","SPACE",2.2),("CLOSE","CLOSE",0.9),
                 ("TYPE INTO APP ↗","INSERT",1.7),("SEND ⏎","ENTER",1.3))
        unit=(width-60-gap*(len(actions)-1))/sum(a[2] for a in actions); x=30
        for label,value,span in actions:
            glass.addSubview_(self.make_key(
                label,value,((x,22),(unit*span,64)),
                2 if value=="INSERT" else 1 if value=="ENTER" else 0))
            x+=unit*span+gap

        self.swipe_trace_view=SwipeTraceView.alloc().initWithController_frame_(
            self,((0,0),(width,height)))
        glass.addSubview_(self.swipe_trace_view)

    @objc.python_method
    def keyboard_hint(self):
        app=str((self.keyboard_target or {}).get("app","the app")).upper()
        return (f"LOOK + WINK TO TYPE INTO {app}   ·   BLINK TO START / NEXT SWIPED WORD"
                "   ·   ESC TO CLOSE")

    @objc.python_method
    def show_keyboard(self, target):
        if self.keyboard_window is None:
            self.build_keyboard()
        # Only start a new message when this is genuinely a new session: the
        # keyboard was closed, or focus moved to a different application.
        previous=self.keyboard_target or {}
        fresh=(not self.keyboard_visible()
               or previous.get("pid") != target.get("pid"))
        self.keyboard_target=target
        if fresh:
            self.keyboard_text=""
            self.swipe.clear()
            self.keyboard_display.setStringValue_("")
            self.refresh_suggestions()
        self.keyboard_title.setStringValue_(self.keyboard_hint())
        # orderFrontRegardless, never makeKeyAndOrderFront_: the target app must
        # keep keyboard focus or the insert has nowhere to land.
        self.keyboard_window.orderFrontRegardless()

    def hideKeyboard_(self, _sender):
        if self.keyboard_window is not None:
            self.swipe_recording=False; self.swipe_path=[]
            self.swipe.clear()
            self.keyboard_window.orderOut_(None)
            if self.status_item is not None:
                self.status_item.button().setTitle_("● OpenGaze · active")

    @objc.python_method
    def keyboard_visible(self):
        return self.keyboard_window is not None and self.keyboard_window.isVisible()

    @objc.python_method
    def make_key(self, title, value, frame, accent=False):
        return KeyView.alloc().initWithFrame_controller_title_value_accent_(
            frame,self,title,value,accent)

    def keyPressed_(self, value):
        value=str(value)
        if value in ("PAUSE","RESUME"):
            self.togglePause_(None); return
        elif value=="EMERGENCY_STOP": self.emergencyStop_(None); return
        elif value=="RECALIBRATE": self.startCalibration_(None); return
        elif self.paused: return
        elif value=="DELETE":
            if self.swipe.slots: self.swipe.delete_word(); self.render_swipe(); return
            self.keyboard_text=self.keyboard_text[:-1]
        elif value=="SPACE": self.keyboard_text+=" "
        elif value=="CLOSE": self.hideKeyboard_(None); return
        elif value=="INSERT":
            self.flush_swipe()
            text=self.keyboard_text; target=self.keyboard_target
            self.hideKeyboard_(None)
            if text and target: insert_text(int(target["pid"]),text)
            return
        elif value=="ENTER":
            # Deliver whatever has been composed, then Return. With an empty
            # buffer this is just Return, which is how you accept a dialog or
            # submit a field without typing anything first.
            self.flush_swipe()
            text=self.keyboard_text; target=self.keyboard_target
            self.hideKeyboard_(None)
            if target:
                if text: insert_text(int(target["pid"]),text)
                press_return(int(target["pid"]))
            return
        elif value.startswith("SLOT:"):
            # Force a swiped word: move it to the front of the last slot.
            word=value.split(":",1)[1]
            if self.swipe.slots:
                slot=self.swipe.slots[-1]
                chosen=next(c for c in slot if c["word"]==word)
                slot.remove(chosen); slot.insert(0,chosen)
            self.render_swipe(); return
        elif value.startswith("SUGGEST:"):
            # A suggestion means two different things depending on where the
            # caret is, and getting it wrong eats a finished word. Mid-word it
            # completes what is being typed and replaces it; after a space it is
            # a predicted NEXT word and must be appended. Unconditionally
            # replacing turned "i need some " + "water" into "i need water".
            word=value.split(":",1)[1]
            if self.keyboard_text and not self.keyboard_text.endswith(" "):
                parts=self.keyboard_text.rstrip().split()
                parts[-1]=word
                self.keyboard_text=" ".join(parts)+" "
            else:
                self.keyboard_text=self.keyboard_text+word+" "
        else: self.keyboard_text+=value
        self.keyboard_display.setStringValue_(self.keyboard_text)
        self.refresh_suggestions()

    @objc.python_method
    def panic_loop(self):
        presses=collections.deque(maxlen=3)
        def callback(proxy,event_type,event,refcon):
            # Triple Escape within 1.5s quits everything; a single Escape
            # only closes the keyboard (on_global_key).
            if Quartz.CGEventGetIntegerValueField(event,Quartz.kCGKeyboardEventKeycode)==53:
                presses.append(time.monotonic())
                if len(presses)==3 and presses[-1]-presses[0]<1.5:
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "quit:", None, False)
            return event
        tap=Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap,Quartz.kCGHeadInsertEventTap,Quartz.kCGEventTapOptionListenOnly,Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),callback,None)
        if tap:
            source=Quartz.CFMachPortCreateRunLoopSource(None,tap,0); Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(),source,Quartz.kCFRunLoopCommonModes); Quartz.CGEventTapEnable(tap,True); Quartz.CFRunLoopRun()


if __name__ == "__main__":
    app=AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller=NativeController.alloc().init()
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))
    atexit.register(controller.release_drag)
    app.run()

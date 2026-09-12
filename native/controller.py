#!/usr/bin/env python3
"""Native macOS blink-to-click controller. Mouse movement stays untouched."""

from __future__ import annotations

import collections
import atexit
import os
from pathlib import Path
import threading
import time

import AppKit
import AVFoundation
from Foundation import NSData, NSObject, NSString, NSTimer
import Vision
import cv2
import objc
import Quartz

from bridge import click, insert_text
from gaze_math import GazeCalibration
from swipe_decoder import SwipeDecoder


TARGETS = ((.08,.08),(.5,.08),(.92,.08),(.08,.5),(.5,.5),(.92,.5),(.08,.92),(.5,.92),(.92,.92))
PID_FILE = Path("/private/tmp/opengaze.pid")
SWIPE_WORDS = Path(__file__).with_name("swipe_words.txt")


def _points(region):
    if region is None or not region.pointCount(): return []
    values = region.normalizedPoints()
    return [values[i] for i in range(region.pointCount())]


def vision_eye_metrics(observation):
    landmarks = observation.landmarks()
    if landmarks is None: return None
    ratios, ears = [], []
    for eye, pupil in ((landmarks.leftEye(), landmarks.leftPupil()),
                       (landmarks.rightEye(), landmarks.rightPupil())):
        contour, pupil_points = _points(eye), _points(pupil)
        if not contour: continue
        xs, ys = [p.x for p in contour], [p.y for p in contour]
        width, height = max(xs)-min(xs), max(ys)-min(ys)
        if width < 1e-5 or height < 1e-5: continue
        if pupil_points:
            px = sum(p.x for p in pupil_points)/len(pupil_points)
            py = sum(p.y for p in pupil_points)/len(pupil_points)
            ratios.append(((px-min(xs))/width, (py-min(ys))/height))
        ears.append(height/width)
    if not ears: return None
    gaze = ((sum(p[0] for p in ratios)/len(ratios),
             sum(p[1] for p in ratios)/len(ratios)) if ratios else (.5,.5))
    return gaze, sum(ears)/len(ears)


class CrosshairView(AppKit.NSView):
    controller = objc.ivar()

    def initWithController_(self, controller):
        self=objc.super(CrosshairView,self).initWithFrame_(((0,0),(52,52)))
        if self is not None: self.controller=controller
        return self

    def drawRect_(self, _rect):
        center=26
        color=(AppKit.NSColor.colorWithRed_green_blue_alpha_(.82,.38,1,.98)
               if self.controller.drag_mode else
               AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.12,.98)
               if time.monotonic()<self.controller.click_flash_until
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
        AppKit.NSColor.whiteColor().setFill()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(((23,23),(6,6))).fill()


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


class CalibrationView(AppKit.NSView):
    controller = objc.ivar()

    def initWithController_(self, controller):
        self = objc.super(CalibrationView, self).initWithFrame_(AppKit.NSScreen.mainScreen().frame())
        if self is not None: self.controller = controller
        return self

    def drawRect_(self, _rect):
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.025,.035,.055,1).setFill()
        AppKit.NSBezierPath.fillRect_(self.bounds())
        bounds = self.bounds()
        AppKit.NSColor.colorWithRed_green_blue_alpha_(.72,.10,.12,1).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((24,bounds.size.height-76),(150,48)),10,10).fill()
        small = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(18),
                 AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()}
        NSString.stringWithString_("EXIT  (Esc)").drawAtPoint_withAttributes_(
            (45,bounds.size.height-61), small)
        if self.controller.failed:
            attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(26),
                     AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()}
            NSString.stringWithString_(
                self.controller.failure_reason
            ).drawAtPoint_withAttributes_((bounds.size.width/2-510,bounds.size.height/2),attrs)
            return

        # Live pupil signal. This intentionally uses the raw within-eye ratio,
        # so users can see exactly what Vision detects before calibration maps
        # that small motion to the full display.
        panel = ((bounds.size.width-300, 35), (260, 190))
        AppKit.NSColor.colorWithWhite_alpha_(.08,.92).setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(panel,14,14).fill()
        live = (self.controller.latest_gaze is not None and
                time.monotonic()-self.controller.latest_seen < .7)
        signal = "EYES DETECTED" if live else "LOOKING FOR EYES…"
        signal_color = (AppKit.NSColor.colorWithRed_green_blue_alpha_(.25,1,.55,1)
                        if live else AppKit.NSColor.orangeColor())
        signal_attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(15),
                        AppKit.NSForegroundColorAttributeName: signal_color}
        NSString.stringWithString_(signal).drawAtPoint_withAttributes_(
            (bounds.size.width-280,190),signal_attrs)
        box=((bounds.size.width-275,55),(210,120))
        if self.controller.latest_frame:
            frame_data=NSData.dataWithBytes_length_(self.controller.latest_frame,
                                                     len(self.controller.latest_frame))
            image=AppKit.NSImage.alloc().initWithData_(frame_data)
            if image is not None: image.drawInRect_(box)
        AppKit.NSColor.colorWithWhite_alpha_(.65,1).setStroke()
        AppKit.NSBezierPath.bezierPathWithRect_(box).stroke()
        if live:
            gx,gy=self.controller.latest_gaze
            px=bounds.size.width-275+max(0,min(1,gx))*210
            py=55+max(0,min(1,gy))*120
            AppKit.NSColor.colorWithRed_green_blue_alpha_(.15,.85,1,1).setFill()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(((px-8,py-8),(16,16))).fill()
        index = min(self.controller.target_index, len(TARGETS)-1)
        x, y = TARGETS[index]
        point = (x*bounds.size.width, (1-y)*bounds.size.height)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.15,1).setFill()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(((point[0]-30,point[1]-30),(60,60))).fill()
        text = f"Look at each dot · {index+1} of {len(TARGETS)}"
        attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(26),
                 AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()}
        NSString.stringWithString_(text).drawAtPoint_withAttributes_(
            (bounds.size.width/2-170,bounds.size.height-65), attrs)

    def mouseDown_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        bounds = self.bounds()
        if point.x <= 190 and point.y >= bounds.size.height-95:
            self.controller.quit_(None)


class NativeController(NSObject):
    def init(self):
        self = objc.super(NativeController, self).init()
        if self is None: return None
        self.running=True; self.control_enabled=True; self.collecting=None; self.failed=False
        self.latest_gaze=None; self.latest_seen=0.0; self.latest_frame=None
        self.failure_reason="Calibration stopped — eyes were not detected. Press R to retry or Escape to exit."
        self.calib_samples=[]; self.calibration=None; self.target_index=0
        self.open_ears=collections.deque(maxlen=120); self.closed_frames=0
        self.closed_since=0.0; self.last_blink=0.0; self.smooth=[.5,.5]
        self.click_flash_until=0.0; self.drag_mode=False
        self.pending_blink=False; self.pending_blink_at=0.0; self.blink_generation=0
        self.keyboard_window=None; self.keyboard_display=None
        self.keyboard_text=""; self.keyboard_target=None
        self.keyboard_glass=None; self.suggestion_buttons=[]
        self.swipe_decoder=SwipeDecoder(SWIPE_WORDS)
        self.swipe_recording=False; self.swipe_path=[]; self.key_centers={}
        self.swipe_trace_view=None
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
        self.crosshair_timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1/60,self,"updateCrosshair:",None,True)
        # A menu-bar control keeps the app out of the way while providing a
        # visible, mouse-accessible exit in addition to the Escape panic key.
        self.status_item=AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        self.status_item.button().setTitle_("◉ Blink Click")
        self.menu=AppKit.NSMenu.alloc().init()
        mode=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Move the mouse normally · blink to click",None,"")
        self.menu.addItem_(mode); self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        quit_item=AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit OpenGaze","quit:","q")
        quit_item.setTarget_(self); self.menu.addItem_(quit_item)
        self.status_item.setMenu_(self.menu)
        threading.Thread(target=self.panic_loop,daemon=True).start()
        self.request_camera_access()
        return self

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
        self.status_item.button().setTitle_("◉ Blink Click · starting camera")
        threading.Thread(target=self.camera_loop,daemon=True).start()

    def startTarget_(self, _sender):
        if self.failed: return
        # Show the target before collecting. Sampling during the eye movement
        # toward a new target compresses all nine measurements toward center.
        self.collecting=None
        self.view.setNeedsDisplay_(True)
        self.performSelector_withObject_afterDelay_("beginCollection:",None,.85)

    def beginCollection_(self, _sender):
        if self.failed: return
        self.collecting=[]
        self.performSelector_withObject_afterDelay_("captureTarget:",None,1.15)

    def captureTarget_(self, _sender):
        samples=self.collecting or []; self.collecting=None
        if samples:
            xs=sorted(v[0] for v in samples); ys=sorted(v[1] for v in samples)
            tx,ty=TARGETS[self.target_index]
            self.calib_samples.append((xs[len(xs)//2],ys[len(ys)//2],tx,ty))
        self.target_index += 1
        if self.target_index < len(TARGETS):
            self.performSelector_withObject_afterDelay_("startTarget:",None,.25); return
        try: self.calibration=GazeCalibration(self.calib_samples)
        except ValueError:
            self.failed=True
            self.failure_reason="Calibration stopped — keep your face well lit and follow each dot. Press R to retry or Escape to exit."
            self.view.setNeedsDisplay_(True); return
        self.control_enabled=True; self.window.orderOut_(None)

    @objc.python_method
    def handle_key(self, event):
        if event.keyCode() == 53: self.quit_(None)
        elif event.keyCode() == 15 and self.failed: self.retry_(None)
        return event

    def retry_(self, _sender):
        self.failed=False; self.target_index=0; self.calib_samples=[]
        self.startTarget_(None)

    def cameraFailed_(self, _sender):
        self.failed=True; self.collecting=None
        self.failure_reason=(
            "Camera access denied. Enable OpenGaze or Terminal in System Settings → "
            "Privacy & Security → Camera, then press Escape and relaunch."
        )
        self.status_item.button().setTitle_("⚠ Blink Click · camera blocked")

    def quit_(self, _sender):
        self.running=False; self.control_enabled=False
        AppKit.NSApp.terminate_(None)

    def updateCrosshair_(self, _timer):
        point=AppKit.NSEvent.mouseLocation()
        self.crosshair_window.setFrameOrigin_((point.x-26,point.y-26))
        if self.swipe_recording:
            self.swipe_path.append((point.x,point.y))
            if self.swipe_trace_view is not None:
                self.swipe_trace_view.setNeedsDisplay_(True)
        elif self.drag_mode:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                Quartz.CGEventCreateMouseEvent(None,Quartz.kCGEventLeftMouseDragged,
                                               point,Quartz.kCGMouseButtonLeft))
        self.crosshair_view.setNeedsDisplay_(True)

    def flashCrosshair_(self, _sender):
        self.click_flash_until=time.monotonic()+.22
        self.crosshair_view.setNeedsDisplay_(True)

    @objc.python_method
    def register_blink(self, now):
        if self.pending_blink and now-self.pending_blink_at <= .65:
            self.pending_blink=False; self.blink_generation+=1
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "toggleDrag:",None,False)
            return
        self.pending_blink=True; self.pending_blink_at=now; self.blink_generation+=1
        self.performSelector_withObject_afterDelay_(
            "commitBlink:",self.blink_generation,.58)

    def handleBlink_(self, timestamp):
        self.register_blink(float(timestamp))

    def commitBlink_(self, generation):
        if not self.pending_blink or int(generation)!=self.blink_generation: return
        self.pending_blink=False
        self.flashCrosshair_(None)
        target=click(show_keyboard=False)
        if target and int(target["pid"]) != os.getpid(): self.showKeyboard_(target)

    def toggleDrag_(self, _sender):
        if self.keyboard_window is not None and self.keyboard_window.isVisible():
            if self.swipe_recording:
                self.finishSwipe_()
            else:
                self.swipe_recording=True; self.drag_mode=True
                point=AppKit.NSEvent.mouseLocation(); self.swipe_path=[(point.x,point.y)]
                self.status_item.button().setTitle_("◆ SWIPE · double blink to finish")
            self.crosshair_view.setNeedsDisplay_(True)
            return
        point=Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        if self.drag_mode:
            kind=Quartz.kCGEventLeftMouseUp; self.drag_mode=False
            self.status_item.button().setTitle_("● Blink Click · active")
        else:
            kind=Quartz.kCGEventLeftMouseDown; self.drag_mode=True
            self.status_item.button().setTitle_("◆ DRAG MODE · double blink to release")
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(None,kind,point,Quartz.kCGMouseButtonLeft))
        self.crosshair_view.setNeedsDisplay_(True)

    def finishSwipe_(self):
        self.swipe_recording=False; self.drag_mode=False
        results=self.swipe_decoder.decode(self.swipe_path)
        self.swipe_path=[]; self.status_item.button().setTitle_("● Blink Click · active")
        if results:
            self.keyboard_text+=results[0]+" "
            self.keyboard_display.setStringValue_(self.keyboard_text)
            self.showSuggestions_(results[1:])

    def showSuggestions_(self, words):
        for button in self.suggestion_buttons: button.removeFromSuperview()
        self.suggestion_buttons=[]
        if not words or self.keyboard_glass is None: return
        width=self.keyboard_window.frame().size.width
        gap=10; button_w=min(190,(width-56-gap*(len(words)-1))/len(words)); total=button_w*len(words)+gap*(len(words)-1); x=(width-total)/2
        y=self.keyboard_window.frame().size.height-194
        for word in words[:5]:
            button=self.makeKey_(word,f"SUGGEST:{word}",((x,y),(button_w,48)))
            self.keyboard_glass.addSubview_(button); self.suggestion_buttons.append(button)
            x+=button_w+gap

    def showKeyboard_(self, target):
        self.keyboard_target=target; self.keyboard_text=""
        screen=AppKit.NSScreen.mainScreen().frame(); width=screen.size.width
        height=min(690,screen.size.height*.72)
        self.keyboard_window=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0,0),(width,height)),AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,False)
        self.keyboard_window.setLevel_(AppKit.NSFloatingWindowLevel)
        self.keyboard_window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)
        glass=AppKit.NSVisualEffectView.alloc().initWithFrame_(((0,0),(width,height)))
        glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(AppKit.NSVisualEffectStateActive)
        self.keyboard_window.setContentView_(glass)
        self.keyboard_glass=glass
        title=AppKit.NSTextField.labelWithString_(
            f"POINT + BLINK TO TYPE INTO {target['app']}")
        title.setFrame_(((28,height-44),(width-56,28)))
        title.setFont_(AppKit.NSFont.boldSystemFontOfSize_(16)); title.setTextColor_(AppKit.NSColor.cyanColor())
        glass.addSubview_(title)
        self.keyboard_display=AppKit.NSTextField.alloc().initWithFrame_(((28,height-112),(width-56,54)))
        self.keyboard_display.setEditable_(False); self.keyboard_display.setSelectable_(False)
        self.keyboard_display.setFont_(AppKit.NSFont.systemFontOfSize_(30))
        self.keyboard_display.setBezeled_(False); self.keyboard_display.setDrawsBackground_(True)
        self.keyboard_display.setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(1,.82))
        self.keyboard_display.setTextColor_(AppKit.NSColor.colorWithWhite_alpha_(.08,1))
        glass.addSubview_(self.keyboard_display)
        rows=("QWERTYUIOP","ASDFGHJKL","ZXCVBNM")
        self.key_centers={}
        y=height-280
        for row in rows:
            gap=10; key_h=72; key_w=min(112,(width-56-gap*(len(row)-1))/len(row))
            total=key_w*len(row)+gap*(len(row)-1); x=(width-total)/2
            for letter in row:
                glass.addSubview_(self.makeKey_(letter,letter.lower(),((x,y),(key_w,key_h))))
                self.key_centers[letter.lower()]=(x+key_w/2,y+key_h/2)
                x+=key_w+gap
            y-=key_h+12
        self.swipe_decoder.set_layout(self.key_centers,key_w)
        actions=(("⌫ DELETE","DELETE",1.0),("SPACE","SPACE",2.0),
                 ("CANCEL","CANCEL",1.0),("TYPE INTO APP ↗","INSERT",1.7))
        gap=10; unit=(width-56-gap*(len(actions)-1))/sum(a[2] for a in actions); x=28
        for label,value,span in actions:
            button=self.makeKey_(label,value,((x,24),(unit*span,70)),value=="INSERT")
            glass.addSubview_(button); x+=unit*span+gap
        self.swipe_trace_view=SwipeTraceView.alloc().initWithController_frame_(
            self,((0,0),(width,height)))
        glass.addSubview_(self.swipe_trace_view)
        self.keyboard_window.makeKeyAndOrderFront_(None); AppKit.NSApp.activateIgnoringOtherApps_(True)

    def makeKey_(self, title, value, frame, accent=False):
        button=AppKit.NSButton.alloc().initWithFrame_(frame)
        button.setTitle_(title); button.setRepresentedObject_(value)
        button.setTarget_(self); button.setAction_("keyboardKey:")
        button.setFont_(AppKit.NSFont.boldSystemFontOfSize_(18 if len(title)>2 else 24))
        button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        if accent: button.setKeyEquivalent_("\r")
        return button

    def keyboardKey_(self, sender):
        value=str(sender.representedObject())
        if value=="DELETE": self.keyboard_text=self.keyboard_text[:-1]
        elif value=="SPACE": self.keyboard_text+=" "
        elif value=="CANCEL": self.keyboard_window.orderOut_(None); return
        elif value=="INSERT":
            text=self.keyboard_text; target=self.keyboard_target
            self.keyboard_window.orderOut_(None)
            if text and target: insert_text(int(target["pid"]),text)
            return
        elif value.startswith("SUGGEST:"):
            word=value.split(":",1)[1]; parts=self.keyboard_text.rstrip().split()
            if parts: parts[-1]=word
            self.keyboard_text=" ".join(parts)+(" " if parts else "")
            self.showSuggestions_([])
        else: self.keyboard_text+=value
        self.keyboard_display.setStringValue_(self.keyboard_text)

    @objc.python_method
    def process(self,gaze,ear,now):
        self.latest_gaze=gaze; self.latest_seen=now
        if ear>.14: self.open_ears.append(ear)
        if not self.control_enabled: return
        ordered=sorted(self.open_ears); threshold=(ordered[len(ordered)//2]*.72) if ordered else .20
        if ear<threshold:
            self.closed_frames+=1
            if self.closed_frames==2: self.closed_since=now
        else:
            if self.closed_frames>=2 and .07<=now-self.closed_since<=.9 and now-self.last_blink>.38:
                self.last_blink=now
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "handleBlink:",now,False)
            self.closed_frames=0

    def refreshGaze_(self, _sender):
        if self.window.isVisible():
            self.view.setNeedsDisplay_(True)
            self.performSelector_withObject_afterDelay_("refreshGaze:",None,.1)

    @objc.python_method
    def camera_loop(self):
        cap=cv2.VideoCapture(0)
        if not cap.isOpened():
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "cameraFailed:", None, False)
            return
        request=Vision.VNDetectFaceLandmarksRequest.alloc().init()
        announced=False
        while self.running and cap.isOpened():
            ok,frame=cap.read()
            if not ok: continue
            good,encoded=cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not good: continue
            self.latest_frame=encoded.tobytes()
            data=NSData.dataWithBytes_length_(encoded.tobytes(),encoded.size)
            # macOS 27 raises NSInvalidArgumentException for an empty bridged
            # Python dictionary here ("key does not exist"). Nil correctly
            # selects Vision's default image options on every supported macOS.
            handler=Vision.VNImageRequestHandler.alloc().initWithData_options_(data,None)
            succeeded,_=handler.performRequests_error_([request],None)
            results=request.results() if succeeded else None
            metrics=vision_eye_metrics(results[0]) if results else None
            if metrics:
                if not announced:
                    announced=True
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "cameraReady:",None,False)
                self.process(metrics[0],metrics[1],time.monotonic())
        cap.release()

    def cameraReady_(self, _sender):
        self.status_item.button().setTitle_("● Blink Click · active")

    @objc.python_method
    def panic_loop(self):
        def callback(proxy,event_type,event,refcon):
            if Quartz.CGEventGetIntegerValueField(event,Quartz.kCGKeyboardEventKeycode)==53:
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
    app.run()

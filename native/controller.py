#!/usr/bin/env python3
"""Native macOS background eye controller. No browser is involved."""

from __future__ import annotations

import collections
import threading
import time

import AppKit
import AVFoundation
from Foundation import NSData, NSObject, NSString
import Vision
import cv2
import objc
import Quartz

from bridge import click, screen_size
from gaze_math import GazeCalibration


TARGETS = ((.08,.08),(.5,.08),(.92,.08),(.08,.5),(.5,.5),(.92,.5),(.08,.92),(.5,.92),(.92,.92))


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
        if not contour or not pupil_points: continue
        xs, ys = [p.x for p in contour], [p.y for p in contour]
        width, height = max(xs)-min(xs), max(ys)-min(ys)
        if width < 1e-5 or height < 1e-5: continue
        px = sum(p.x for p in pupil_points)/len(pupil_points)
        py = sum(p.y for p in pupil_points)/len(pupil_points)
        ratios.append(((px-min(xs))/width, (py-min(ys))/height))
        ears.append(height/width)
    if not ratios: return None
    gaze = (sum(p[0] for p in ratios)/len(ratios), sum(p[1] for p in ratios)/len(ratios))
    return gaze, sum(ears)/len(ears)


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
        self.running=True; self.control_enabled=False; self.collecting=None; self.failed=False
        self.latest_gaze=None; self.latest_seen=0.0; self.latest_frame=None
        self.failure_reason="Calibration stopped — eyes were not detected. Press R to retry or Escape to exit."
        self.calib_samples=[]; self.calibration=None; self.target_index=0
        self.open_ears=collections.deque(maxlen=120); self.closed_frames=0
        self.closed_since=0.0; self.last_blink=0.0; self.smooth=[.5,.5]
        screen=AppKit.NSScreen.mainScreen().frame()
        self.view=CalibrationView.alloc().initWithController_(self)
        self.window=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(screen,AppKit.NSWindowStyleMaskBorderless,AppKit.NSBackingStoreBuffered,False)
        self.window.setLevel_(AppKit.NSMainMenuWindowLevel+2); self.window.setContentView_(self.view)
        self.window.setBackgroundColor_(AppKit.NSColor.blackColor()); self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self.key_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown, self.handle_key)
        threading.Thread(target=self.panic_loop,daemon=True).start()
        self.request_camera_access()
        self.performSelector_withObject_afterDelay_("startTarget:",None,1.5)
        self.performSelector_withObject_afterDelay_("refreshGaze:",None,.1)
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
        self.view.setNeedsDisplay_(True)

    def quit_(self, _sender):
        self.running=False; self.control_enabled=False
        AppKit.NSApp.terminate_(None)

    @objc.python_method
    def process(self,gaze,ear,now):
        self.latest_gaze=gaze; self.latest_seen=now
        if self.collecting is not None: self.collecting.append(gaze)
        if ear>.14: self.open_ears.append(ear)
        if not self.control_enabled or not self.calibration: return
        ordered=sorted(self.open_ears); threshold=(ordered[len(ordered)//2]*.72) if ordered else .20
        if ear<threshold:
            self.closed_frames+=1
            if self.closed_frames==2: self.closed_since=now
        else:
            if self.closed_frames>=2 and .07<=now-self.closed_since<=.9 and now-self.last_blink>.38:
                self.last_blink=now; click()
            self.closed_frames=0
        x,y=self.calibration.map(*gaze)
        self.smooth[0]=self.smooth[0]*.70+x*.30; self.smooth[1]=self.smooth[1]*.70+y*.30
        width,height=screen_size(); point=Quartz.CGPointMake(self.smooth[0]*width,self.smooth[1]*height)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,Quartz.CGEventCreateMouseEvent(None,Quartz.kCGEventMouseMoved,point,Quartz.kCGMouseButtonLeft))

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
        while self.running and cap.isOpened():
            ok,frame=cap.read()
            if not ok: continue
            good,encoded=cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not good: continue
            self.latest_frame=encoded.tobytes()
            data=NSData.dataWithBytes_length_(encoded.tobytes(),encoded.size)
            handler=Vision.VNImageRequestHandler.alloc().initWithData_options_(data,{})
            succeeded,_=handler.performRequests_error_([request],None)
            results=request.results() if succeeded else None
            metrics=vision_eye_metrics(results[0]) if results else None
            if metrics: self.process(metrics[0],metrics[1],time.monotonic())
        cap.release()

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
    app.run()

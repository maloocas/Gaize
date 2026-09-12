#!/usr/bin/env python3
"""Native macOS background eye controller. No browser is involved."""

from __future__ import annotations

import collections
import threading
import time

import AppKit
from Foundation import NSData, NSObject, NSTimer
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
        index = min(self.controller.target_index, len(TARGETS)-1)
        x, y = TARGETS[index]; bounds = self.bounds()
        point = (x*bounds.size.width, (1-y)*bounds.size.height)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1,.82,.15,1).setFill()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(((point[0]-30,point[1]-30),(60,60))).fill()
        text = f"Look at each dot · {index+1} of {len(TARGETS)}"
        attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(26),
                 AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()}
        text.drawAtPoint_withAttributes_((bounds.size.width/2-170,bounds.size.height-65),attrs)


class NativeController(NSObject):
    def init(self):
        self = objc.super(NativeController, self).init()
        if self is None: return None
        self.running=True; self.control_enabled=False; self.collecting=None
        self.calib_samples=[]; self.calibration=None; self.target_index=0
        self.open_ears=collections.deque(maxlen=120); self.closed_frames=0
        self.closed_since=0.0; self.last_blink=0.0; self.smooth=[.5,.5]
        screen=AppKit.NSScreen.mainScreen().frame()
        self.view=CalibrationView.alloc().initWithController_(self)
        self.window=AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(screen,AppKit.NSWindowStyleMaskBorderless,AppKit.NSBackingStoreBuffered,False)
        self.window.setLevel_(AppKit.NSMainMenuWindowLevel+2); self.window.setContentView_(self.view)
        self.window.setBackgroundColor_(AppKit.NSColor.blackColor()); self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        threading.Thread(target=self.camera_loop,daemon=True).start()
        threading.Thread(target=self.panic_loop,daemon=True).start()
        self.performSelector_withObject_afterDelay_("startTarget:",None,1.5)
        return self

    def startTarget_(self, _sender):
        self.collecting=[]
        self.view.setNeedsDisplay_(True)
        self.performSelector_withObject_afterDelay_("captureTarget:",None,.75)

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
            self.target_index=0; self.calib_samples=[]
            self.performSelector_withObject_afterDelay_("startTarget:",None,1.0); return
        self.control_enabled=True; self.window.orderOut_(None)

    @objc.python_method
    def process(self,gaze,ear,now):
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

    @objc.python_method
    def camera_loop(self):
        cap=cv2.VideoCapture(0)
        request=Vision.VNDetectFaceLandmarksRequest.alloc().init()
        while self.running and cap.isOpened():
            ok,frame=cap.read()
            if not ok: continue
            good,encoded=cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not good: continue
            data=NSData.dataWithBytes_length_(encoded.tobytes(),encoded.size)
            handler=Vision.VNImageRequestHandler.alloc().initWithData_options_(data,{})
            succeeded,_=handler.performRequests_error_([request],None)
            results=request.results() if succeeded else None
            metrics=vision_eye_metrics(results[0]) if results else None
            if metrics: self.process(metrics[0],metrics[1],time.monotonic())
        cap.release()

    @objc.python_method
    def panic_loop(self):
        presses=[]
        def callback(proxy,event_type,event,refcon):
            if Quartz.CGEventGetIntegerValueField(event,Quartz.kCGKeyboardEventKeycode)==53:
                now=time.monotonic(); presses.append(now); del presses[:-3]
                if len(presses)==3 and now-presses[0]<=2:
                    self.control_enabled=False; presses.clear()
            return event
        tap=Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap,Quartz.kCGHeadInsertEventTap,Quartz.kCGEventTapOptionListenOnly,Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),callback,None)
        if tap:
            source=Quartz.CFMachPortCreateRunLoopSource(None,tap,0); Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(),source,Quartz.kCFRunLoopCommonModes); Quartz.CGEventTapEnable(tap,True); Quartz.CFRunLoopRun()


if __name__ == "__main__":
    app=AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller=NativeController.alloc().init()
    app.run()

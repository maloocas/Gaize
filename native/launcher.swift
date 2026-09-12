import Foundation
import Darwin

let root = Bundle.main.bundleURL
    .deletingLastPathComponent()
let python = root.appendingPathComponent(".native-venv/bin/python").path
let controller = root.appendingPathComponent("native/controller.py").path
setenv("MPLCONFIGDIR", "/private/tmp/opengaze-mpl", 1)
setenv("XDG_CACHE_HOME", "/private/tmp/opengaze-cache", 1)
let arguments = [python, controller]
let cArguments = arguments.map { strdup($0) } + [nil]
execv(python, cArguments)
perror("OpenGaze could not start")
exit(1)

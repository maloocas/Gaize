from native.gaze_math import GazeCalibration


def samples(xs=(.68, .50, .32), ys=(.30, .50, .70)):
    result = []
    for row, target_y in enumerate((.08, .50, .92)):
        for col, target_x in enumerate((.08, .50, .92)):
            result.append((xs[col], ys[row], target_x, target_y))
    return result


def test_calibration_expands_observed_range_to_full_screen():
    calibration = GazeCalibration(samples())
    assert calibration.map(.68, .30) == (0.0, 0.0)
    assert calibration.map(.50, .50) == (.5, .5)
    assert calibration.map(.32, .70) == (1.0, 1.0)


def test_calibration_supports_non_mirrored_camera_signal():
    calibration = GazeCalibration(samples(xs=(.30, .50, .70)))
    assert calibration.map(.30, .50)[0] == 0.0
    assert calibration.map(.70, .50)[0] == 1.0


def test_mapping_clamps_beyond_calibrated_edges():
    calibration = GazeCalibration(samples())
    assert calibration.map(.90, .10) == (0.0, 0.0)
    assert calibration.map(.10, .90) == (1.0, 1.0)

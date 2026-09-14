"""Isolated camera/inference worker. IPC transports landmarks, never images."""
import multiprocessing as mp
import queue
import time
from contextlib import ExitStack


def latest_put(q, value):
    try:
        q.put_nowait(value)
        return 0
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            return 1
        try:
            q.put_nowait(value)
        except queue.Full:
            pass
        return 1


def worker(config, results, stopping):
    import hand_tracking as h
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except ImportError:
        pass
    started, cpu = time.monotonic(), time.process_time()
    dropped_results = 0
    try:
        with ExitStack() as cleanup:
            backend = h.make_backend(config)
            cleanup.callback(backend.close)
            camera = h.make_camera(config)
            if not isinstance(camera, h.SimulatedCamera):
                camera = h.ThreadedCamera(camera, config['target_fps'])
            cleanup.callback(camera.stop)
            camera.start()
            frames = 0
            overload = 0
            while not stopping.is_set():
                frame = None
                begin = time.monotonic()
                if isinstance(camera, h.ThreadedCamera):
                    packet, _ = camera.read_latest()
                    if packet is None:
                        stopping.wait(.005)
                        continue
                    frame, captured, capture_s = packet
                else:
                    frame, _ = camera.read_latest()
                    captured, capture_s = begin, time.monotonic() - begin
                    if frame is None:
                        latest_put(results, {'done': True})
                        return
                infer_start = time.monotonic()
                try:
                    hands = backend.detect(frame, captured)
                finally:
                    frame = None
                    packet = None
                now = time.monotonic()
                frames += 1
                infer_s = now - infer_start
                stats = camera.statistics() if isinstance(camera, h.ThreadedCamera) else {
                    'captured_frames': frames, 'fps_capture': frames / max(now - started, .001),
                    'dropped_frames': 0}
                message = dict(stats, hands=hands, captured=captured, capture_s=capture_s,
                               inference_s=infer_s, inference_frames=frames,
                               fps_inference=frames / max(now - started, .001),
                               result_drops=dropped_results, backend=backend.name, camera=camera.name,
                               target_fps=config['target_fps'],
                               worker_cpu_s=time.process_time() - cpu,
                               worker_memory_mb=h.read_memory_mb())
                dropped_results += latest_put(results, message)
                # Adapt at most once per 20 inferences, not on every desktop poll.
                overload = overload + 1 if infer_s > 1.25 / config['target_fps'] else max(0, overload - 1)
                if overload >= 20 and config['target_fps'] > 5:
                    config['target_fps'] = max(5, int(config['target_fps'] * .8))
                    if isinstance(camera, h.ThreadedCamera):
                        camera.fps = config['target_fps']
                        camera.set_fps(camera.fps)
                    overload = 0
                stopping.wait(max(0, 1 / config['target_fps'] - (time.monotonic() - begin)))
    except BaseException as exc:
        latest_put(results, {'error': type(exc).__name__ + ': ' + str(exc)})


class Pipeline:
    def __init__(self, config, target=worker):
        ctx = mp.get_context('spawn')
        self.results = ctx.Queue(maxsize=1)
        self.stopping = ctx.Event()
        self.process = ctx.Process(target=target, args=(dict(config), self.results, self.stopping), daemon=True)

    def start(self):
        self.process.start()
        return self

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            if self.process.exitcode is not None:
                return {'error': 'Camera worker exited (' + str(self.process.exitcode) + ').'}
            return None

    def close(self):
        self.stopping.set()
        if self.process.pid:
            self.process.join(.4)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(1)
            self.process.close()
        self.results.cancel_join_thread()
        self.results.close()

from environs import Env
from gevent import monkey  # type: ignore
from gunicorn.workers.ggevent import GeventWorker  # type: ignore


class OTelAwareGeventWorker(GeventWorker):
    @classmethod
    def patch(cls) -> None:
        env = Env()
        if env.bool("FF_ENABLE_OTEL", default=False):
            # OpenTelemetry auto-instrumentation patches SSL already; avoid double-patching.
            monkey.patch_all(ssl=False)
        else:
            monkey.patch_all()

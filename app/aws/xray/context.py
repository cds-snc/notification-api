import logging

from aws_xray_sdk.core.context import Context
from aws_xray_sdk.core.exceptions.exceptions import SegmentNotFoundException

log = logging.getLogger(__name__)

MISSING_SEGMENT_MSG = "cannot find the current segment/subsegment, please make sure you have a segment open"
SUPPORTED_CONTEXT_MISSING = ("RUNTIME_ERROR", "LOG_ERROR", "LOG_WARNING", "IGNORE_ERROR")
CXT_MISSING_STRATEGY_KEY = "AWS_XRAY_CONTEXT_MISSING"


class NotifyContext(Context):
    """
    This is a custom context class that has more sensitive logging levels
    than the default thread local context class.

    For example, if there is a check on the current segment, no errors would
    be logged but rather warn or info messages would be logged.

    The context parent class is the default storage one that works using
    a threadlocal. The same technical constraints and feature apply.
    """

    def __init__(self, context_missing="LOG_WARNING"):
        super().__init__(context_missing)

    def put_segment(self, segment):
        """
        Store the segment created by ``xray_recorder`` to the context.
        It overrides the current segment if there is already one.
        """
        super().put_segment(segment)

    def end_segment(self, end_time=None):
        """
        End the current active segment.

        :param float end_time: epoch in seconds. If not specified the current
            system time will be used.
        """
        super().end_segment(end_time)

    def put_subsegment(self, subsegment):
        """
        Store the subsegment created by ``xray_recorder`` to the context.
        If you put a new subsegment while there is already an open subsegment,
        the new subsegment becomes the child of the existing subsegment.
        """
        super().put_subsegment(subsegment)

    def end_subsegment(self, end_time=None):
        """
        End the current active segment. Return False if there is no
        subsegment to end.

        :param float end_time: epoch in seconds. If not specified the current
            system time will be used.
        """
        return super().end_subsegment(end_time)

    def get_trace_entity(self):
        """
        Return the current trace entity(segment/subsegment). If there is none,
        it behaves based on pre-defined ``context_missing`` strategy.
        If the SDK is disabled, returns a DummySegment
        """
        return super().get_trace_entity()

    def set_trace_entity(self, trace_entity):
        """
        Store the input trace_entity to local context. It will overwrite all
        existing ones if there is any.
        """
        super().set_trace_entity(trace_entity)

    def clear_trace_entities(self):
        """
        clear all trace_entities stored in the local context.
        In case of using threadlocal to store trace entites, it will
        clean up all trace entities created by the current thread.
        """
        super().clear_trace_entities()

    def handle_context_missing(self):
        """
        Called whenever there is no trace entity to access or mutate.
        """
        if self.context_missing == "RUNTIME_ERROR":
            raise SegmentNotFoundException(MISSING_SEGMENT_MSG)
        elif self.context_missing == "LOG_ERROR":
            log.error(MISSING_SEGMENT_MSG)
        elif self.context_missing == "LOG_WARNING":
            log.warning(MISSING_SEGMENT_MSG)

    def _is_subsegment(self, entity):
        return super()._is_subsegment(entity)

    @property
    def context_missing(self):
        return self._context_missing

    @context_missing.setter
    def context_missing(self, value):
        if value not in SUPPORTED_CONTEXT_MISSING:
            log.warning("specified context_missing not supported, using default.")
            return

        self._context_missing = value

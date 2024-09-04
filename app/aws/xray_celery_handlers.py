import logging

from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core.utils import stacktrace
from aws_xray_sdk.ext.util import construct_xray_header, inject_trace_header

__all__ = (
    "xray_after_task_publish",
    "xray_before_task_publish",
    "xray_task_failure",
    "xray_task_postrun",
    "xray_task_prerun",
)

logger = logging.getLogger("celery_aws_xray_sdk_extension")

CELERY_NAMESPACE = "celery"


def xray_before_task_publish(
    sender=None, headers=None, exchange=None, routing_key=None, properties=None, declare=None, retry_policy=None, **kwargs
):
    logger.info(f"xray-celery: before publish: sender={sender}, headers={headers}, kwargs={kwargs}")
    headers = headers if headers else {}
    task_id = headers.get("id")
    current_segment = xray_recorder.current_segment()
    # Checks if there is a current segment to create a subsegment,
    # otherwise we might be in a starter task. The prerun handler will
    # create the segment for us down the road as it will be called after.
    if current_segment:
        subsegment = xray_recorder.begin_subsegment(name=sender, namespace="remote")
        if subsegment:
            subsegment.put_metadata("task_id", task_id, namespace=CELERY_NAMESPACE)
            inject_trace_header(headers, subsegment)
        else:
            logger.error(
                "xray-celery: Failed to create a X-Ray subsegment on task publish", extra={"celery": {"task_id": task_id}}
            )
    else:
        logger.warn("xray-celery: No parent segment found for task {task_id} when trying to create subsegment", task_id)


def xray_after_task_publish(headers=None, body=None, exchange=None, routing_key=None, **kwargs):
    logger.info(
        f"xray-celery: after publish: headers={headers}, body={body}, exchange={exchange}, routing_key={routing_key}, kwargs={kwargs}"
    )
    if xray_recorder.current_subsegment():
        xray_recorder.end_subsegment()
    else:
        logger.warn(
            f"xray-celery: Skipping subsegment closing after publish as no subsegment was found: {headers}"
        )


def xray_task_prerun(task_id=None, task=None, args=None, **kwargs):
    logger.info(f"xray-celery: prerun: task_id={task_id}, task={task}, kwargs={kwargs}")
    xray_header = construct_xray_header(task.request)
    segment = xray_recorder.begin_segment(name=task.name, traceid=xray_header.root, parent_id=xray_header.parent)
    segment.save_origin_trace_header(xray_header)
    segment.put_annotation("routing_key", task.request.properties["delivery_info"]["routing_key"])
    segment.put_annotation("task_name", task.name)
    segment.put_metadata("task_id", task_id, namespace=CELERY_NAMESPACE)


def xray_task_postrun(task_id=None, task=None, args=None, **kwargs):
    logger.info(f"xray-celery: postrun: kwargs={kwargs}")
    xray_recorder.end_segment()


def xray_task_failure(task_id=None, exception=None, **kwargs):
    logger.info(f"xray-celery: failure: task_id={task_id}, e={exception}, kwargs={kwargs}")
    segment = xray_recorder.current_segment()
    if not segment:
        logger.error(
            "xray-celery: Failed to get the current segment on task failure", extra={"celery": {"task_id": kwargs.get("task_id")}}
        )
        return

    if exception:
        stack = stacktrace.get_stacktrace(limit=xray_recorder._max_trace_back)
        segment.add_exception(exception, stack)

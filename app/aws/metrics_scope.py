# Copyright 2019 Amazon.com, Inc. or its affiliates.
# Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import inspect
from functools import wraps

from aws_embedded_metrics.logger.metrics_logger_factory import (  # type: ignore
    create_metrics_logger,
)


def metric_scope(fn):  # type: ignore

    if asyncio.iscoroutinefunction(fn):

        @wraps(fn)
        async def wrapper(*args, **kwargs):  # type: ignore
            logger = create_metrics_logger()
            if "metrics" in inspect.signature(fn).parameters:
                kwargs["metrics"] = logger
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                raise e
            finally:
                await logger.flush()

        return wrapper
    else:

        @wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore
            logger = create_metrics_logger()
            if "metrics" in inspect.signature(fn).parameters:
                kwargs["metrics"] = logger
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                raise e
            finally:
                try:
                    loop = (
                        asyncio.get_event_loop()
                    )  # This will fail to create a new event loop if called outside the main thread. https://bugs.python.org/issue39381
                except RuntimeError as ex:
                    if "There is no current event loop in thread" in str(ex):
                        loop = asyncio.new_event_loop()  # https://github.com/awslabs/aws-embedded-metrics-python/issues/14
                        asyncio.set_event_loop(loop)
                    else:
                        raise

                if not loop.is_running:
                    loop.run_until_complete(logger.flush())

        return wrapper

import httpx
from typing import Optional, Any, Union
from functools import wraps
from inspect import iscoroutinefunction
from time import perf_counter
import traceback as tb
import base64
from dataclasses import is_dataclass, asdict
import uuid
import numpy as np
from datetime import datetime, date
from decimal import Decimal
import enum
import pandas as pd
from pathlib import Path

# Handles parsing data into JSON acceptable format

JSONSafe: Any = lambda value: (
    value                         if value is None                                                      # None → None
    else None if (not isinstance(value, (pd.DataFrame, pd.Series, np.ndarray, list, tuple, dict, set)) and pd.isna(value)) # In case of NA (NaN, NaT, NA) → use None
    else value                    if isinstance(value, (str, int, float, bool))                         # Basic types → already JSON safe
    else value.isoformat()        if isinstance(value, (date, datetime))                                # Datetime-like → ISO8601 string
    else str(value)               if isinstance(value, uuid.UUID)                                       # UUID → string
    else value.value              if isinstance(value, enum.Enum)                                       # Enum → value or .name
    else list(value)              if isinstance(value, set)                                             # Set → list
    else str(value)               if isinstance(value, Path)                                            # Paths → string
    else float(value)             if isinstance(value, Decimal)                                         # Decimal → float
    else {"real": value.real, "imag": value.imag} if isinstance(value, complex)                         # complex → dict
    else base64.b64encode(value).decode('utf-8') if isinstance(value, (bytes, bytearray))               # Bytes → base64
    else JSONSafe(value.tolist()) if isinstance(value, np.ndarray)                                      # Numpy Array → process values
    else JSONSafe(value.item())   if isinstance(value, np.generic)                                      # Numpy Number → process values
    else {f: JSONSafe(getattr(value, f)) for f in value._fields} if isinstance(value, tuple) and hasattr(value, "_fields") # Named Tuples
    else [JSONSafe(v) for v in value] if isinstance(value, (list, tuple))                               # List/tuple → process each element
    else {k:JSONSafe(v) for k,v in value.items()} if isinstance(value, dict)                            # Dict → process values
    else [JSONSafe(row) for row in value.to_dict(orient="records")] if isinstance(value, pd.DataFrame)  # Dataframe → Safe Rows
    else {k:JSONSafe(v) for k,v in value.to_dict().items()} if isinstance(value, pd.Series)             # Series → process values
    else JSONSafe(asdict(value)) if is_dataclass(value)                                                 # Dataclass → dict
    else {k:JSONSafe(v) for k,v in vars(value).items()} if hasattr(value, "__dict__")                   # (Fallback) Use a safe dict if able
    else JSONSafe(value.__json__()) if hasattr(value, '__json__')                                       # (Fallback) JSONSafe JSON if available
    else repr(value) # (Fallback - All obj. have repr str)
)

class void:
    '''Simple print replacement for unified logging'''
    def __init__(self):
        pass

    def __call__(self, *args, **kwds) -> None:
        print(*args)
        return

    def exception(self, exc: Exception, msg: str = "", **kwargs):
        message = f"{msg}: {type(exc).__name__}: {exc}" if msg else f"{type(exc).__name__}: {exc}"
        self(message, log_level="ERROR", **kwargs)

        _tb = ''.join(tb.format_exception(type(exc), exc, exc.__traceback__))
        self(_tb, log_level="ERROR", **kwargs)

class GCNotifyAPI:
    '''Small asynchronous client for GC Notify'''

    _void = void()

    def __init__(
            self,
            api_key: str,
            base_url: str = "https://api.notification.canada.ca",
            timeout: float = 30.0,
            enable_jsonsafe: bool = True,
            _Tee: Optional[Union[object, void]] = None,  # Substitute for your logging mechanism
            _trace: bool = True
        ):

        self.T = _Tee or GCNotifyAPI._void
        self.jsonsafe = enable_jsonsafe
        self._trace = _trace

        # Local Variables
        LOCAL: dict[str, str] = self._hook(
            {
                'api_key': api_key or None,
                'base_url': base_url or None
            }
        )

        API_KEY = LOCAL['api_key']
        BASE_URL = LOCAL['base_url'].rstrip("/")
        
        HEADERS = {
            "Authorization": f"ApiKey-v1 {API_KEY}",
            "Content-Type": "application/json",
        }

        # AsyncClient setup
        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=HEADERS,
            timeout=timeout
        )

    @staticmethod
    def trace(func):
        def log_start(self, kwargs):
            if self._trace:
                self.T(f'{self!r} Exec "{func.__name__}" kwargs={kwargs!r} ....', log_level='DEBUG')

        def log_finish(self, start):
            if self._trace:
                elapsed = perf_counter() - start
                self.T(f'{self!r} .... "{func.__name__}" in {elapsed:.4f}s', log_level='DEBUG')

        if iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(self, *args, **kwargs):
                start = perf_counter()
                log_start(self, kwargs)
                try:
                    result = await func(self, *args, **kwargs)
                except Exception as exc:
                    self.T.exception(exc)
                    raise
                log_finish(self, start)
                return result

            return async_wrapper

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start = perf_counter()
            log_start(self, kwargs)
            try:
                result = func(self, *args, **kwargs)
            except Exception as exc:
                self.T.exception(exc)
                raise
            log_finish(self, start)
            return result

        return wrapper

    @staticmethod
    def _hook(DICT:dict[str, str]):
        '''Simple clean pass for variables in dict, ensures values are set.'''
        for key, value in DICT.items():
            if (not value) or (value is None):
                raise ValueError(f'Missing ({key})')
            if not isinstance(value, str):
                raise TypeError(f'{value=} (CANNOT BE {type(value)}, MUST BE STR)')
            if len(value) == 0:
                raise ValueError(f'Missing ({key})')
        return DICT
    
    @staticmethod
    def _strap(DICT:dict, key, value):
        '''Filter control conditions to exclude `None` and empty strings'''
        if isinstance(value, str) and len(value) > 0:
            DICT[key] = value
        elif isinstance(value, (bool, list, dict)):
            DICT[key] = value
        return DICT

    @trace
    async def request(
            self,
            method: str,
            endpoint: str,
            *,
            params: Optional[dict[str, Any]] = None,
            json: Optional[dict[str, Any]] = None,
            accept: str = 'application/json'
        ):

        if not self.client:
            raise RuntimeError('Client was closed.')

        if (self.jsonsafe) and (json is not None):
            json = JSONSafe(json)

        try:
            response = await self.client.request(
                method,
                endpoint,
                params=params,
                json=json,
                headers={"Accept": accept}
            )

        except Exception as e:
            self.T.exception(e, f'Request Failed ({method=} {endpoint=} {params=} {json=})')

        if not response.is_success:
            exc = httpx.HTTPStatusError(
                f"GC Notify returned HTTP {response.status_code}: {response.text[:2000]}",
                request=response.request,
                response=response
            )
            self.T.exception(exc)
            raise exc

        if not response.content:
            return None

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.json()

        return response.content

    async def close(self) -> None:
        await self.client.aclose()
        self.client = None
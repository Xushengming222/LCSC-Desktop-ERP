"""Base infrastructure for Qt-based ViewModels.

The Android app builds UI state with ``combine(...) { ... }.stateIn(scope, ...)``:
whenever any source Flow emits, the combiner runs and the StateFlow value updates.
This module replicates that pattern with Qt Signals:

* ``ViewModel`` holds an opaque ``ui_state`` snapshot and emits
  ``ui_state_changed`` whenever the snapshot is replaced.
* Subclasses implement ``_recompute()`` to build the latest snapshot from the
  repositories. They wire the relevant ``changed``/``preferences_changed``/
  ``language_changed`` signals to ``_schedule_recompute``, which coalesces
  multiple emits in the same event-loop tick into a single recompute.
* Long-running work (network lookups, backup import/export) runs on the shared
  ``QThreadPool``. The worker is a plain ``QRunnable`` (NOT a QObject — PySide6
  crashes on ``QObject+QRunnable`` multiple inheritance when the pool calls
  ``run()``). It emits its result via a ``_ResultBridge`` QObject that lives on
  the GUI thread; Qt queues the cross-thread emission automatically, so the
  callback always runs on the GUI thread — mirroring ``viewModelScope.launch``
  dispatching back to ``Dispatchers.Main``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot


class _ResultBridge(QObject):
    """GUI-thread signal relay for worker results.

    A single bridge is owned by each ``ViewModel`` and lives on the GUI thread.
    Workers emit ``result_ready`` from the thread pool; Qt auto-queues the
    emission to the GUI thread because the bridge's thread affinity differs.
    """

    result_ready = Signal(object, object, object)  # on_done, result, error


class _Worker(QRunnable):
    """Plain QRunnable that runs ``fn`` then relays its result via the bridge.

    Deliberately NOT a QObject: PySide6 crashes when ``QThreadPool.start()``
    invokes ``run()`` on a ``QObject+QRunnable`` multiple-inheritance instance.
    """

    def __init__(self, fn: Callable[[], Any], on_done: Callable[[Any, Optional[Exception]], None], bridge: _ResultBridge) -> None:
        super().__init__()
        self._fn = fn
        self._on_done = on_done
        self._bridge = bridge

    def run(self) -> None:  # noqa: D401 - QRunnable override
        try:
            result: Any = self._fn()
            error: Optional[Exception] = None
        except Exception as exc:  # noqa: BLE001 - surfaced to caller
            result = None
            error = exc
        self._bridge.result_ready.emit(self._on_done, result, error)


class ViewModel(QObject):
    """Base class for all view models.

    Subclasses set ``self._state`` inside ``_recompute`` and rely on
    ``_schedule_recompute`` (wired to repository signals) to emit
    ``ui_state_changed``.
    """

    ui_state_changed = Signal()

    def __init__(self, thread_pool: Optional[QThreadPool] = None) -> None:
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state: Any = None
        self._recompute_scheduled = False
        self._bridge = _ResultBridge()
        self._bridge.moveToThread(self.thread())
        self._bridge.result_ready.connect(self._dispatch_result, Qt.QueuedConnection)

    # ---- state access ----
    @property
    def ui_state(self) -> Any:
        return self._state

    # ---- recompute scheduling ----
    def _schedule_recompute(self) -> None:
        """Coalesce multiple source-emits in the same event-loop tick into one recompute."""
        if self._recompute_scheduled:
            return
        self._recompute_scheduled = True
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._do_recompute)

    @Slot()
    def _do_recompute(self) -> None:
        self._recompute_scheduled = False
        self._recompute()
        self.ui_state_changed.emit()

    def _recompute(self) -> None:
        """Override to rebuild ``self._state`` from repositories."""
        pass

    def _emit_changed(self) -> None:
        self.ui_state_changed.emit()

    # ---- async helper ----
    def _run_async(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any, Optional[Exception]], None],
    ) -> None:
        """Run ``fn`` on the thread pool; call ``on_done(result, error)`` on the GUI thread."""
        worker = _Worker(fn, on_done, self._bridge)
        worker.setAutoDelete(True)
        self._thread_pool.start(worker)

    @Slot(object, object, object)
    def _dispatch_result(self, on_done, result, error) -> None:
        on_done(result, error)

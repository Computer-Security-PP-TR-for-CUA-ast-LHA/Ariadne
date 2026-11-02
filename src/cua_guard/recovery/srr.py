"""Optional original SRR planner, kept in its own research environment.

This only produces a native candidate plan. It cannot quarantine, grant access,
execute writers/tools or replace the stricter Ariadne completeness checks.
"""
import json
from pathlib import Path
import subprocess
import sys
from .contracts import RecoveryError, canonical, identity


class SRRNativePlanner:
    identity = 'selective-revocation-replay/d7bcb32740156cb985fae0ee93caba35ee45e67e'

    def __init__(self, checkout, *, python=sys.executable, timeout=30):
        self.checkout = str(Path(checkout).resolve())
        self.python, self.timeout = python, timeout

    def plan(self, native_run_dir, roots):
        if not roots:
            raise RecoveryError('unknown_root')
        for root in roots:
            identity(root)
        try:
            result = subprocess.run([self.python, '-I', str(Path(__file__).with_name('_srr_worker.py')), self.checkout],
                input=canonical({'run_dir': str(Path(native_run_dir).resolve()), 'roots': list(roots)}),
                encoding='utf-8', capture_output=True, timeout=self.timeout, check=False)
            if result.returncode:
                raise RecoveryError('srr_backend_rejected')
            plan = json.loads(result.stdout)
            if plan['mode'] not in {'writer_only', 'coarse_rollback'}:
                raise ValueError('invalid mode')
            return plan
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            raise RecoveryError('srr_backend_unavailable') from exc

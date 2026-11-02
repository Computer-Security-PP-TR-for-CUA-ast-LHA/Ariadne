"""Optional real upstream reuse, not a reimplementation of scoped authorization.

Executes the pinned MIT upstream in an isolated Python process. Checkout is host
configuration. No downloads, pip installs, shell, model calls or secret logging.
"""
import json
from pathlib import Path
import subprocess
import sys
from .contracts import RecoveryError, canonical


class TMAParameterRecovery:
    identity = 'mem-inv-bench/cf3c9a4ca9f0478000d6aa26eb268b875232d34b'

    def __init__(self, checkout, *, timeout=15):
        self.checkout = str(Path(checkout).resolve())
        if not 0 < timeout <= 60:
            raise ValueError('timeout must be in (0,60]')
        self.timeout = timeout

    def recover_parameters(self, *, authorities, policy, records, operation, subject, now, revoked=(), k=2):
        """Authorities: channel -> {domain,key_hex,scopes:[[op,subject,field]]}.

        Keys, authenticated packets, clock and revocations must come from the host.
        This produces a PROPOSAL, not an execution grant. Never pass this result
        straight to SafeExecutor.authorizer; independently recheck at dispatch.
        """
        encoded = canonical(dict(authorities=authorities, policy=policy, records=records,
                                 operation=operation, subject=subject, now=now, revoked=revoked, k=k))
        if len(encoded) > 2_000_000:
            raise RecoveryError('authority_input_budget_exceeded')
        try:
            result = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('_tma_worker.py')), self.checkout],
                input=encoded, encoding='utf-8', capture_output=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecoveryError('authority_backend_unavailable') from exc
        if result.returncode != 0:
            raise RecoveryError('authority_backend_rejected')
        try:
            output = json.loads(result.stdout)
            if output.get('status') not in {'available', 'unavailable', 'ambiguous'}:
                raise ValueError('invalid status')
            return output
        except (ValueError, AttributeError) as exc:
            raise RecoveryError('authority_backend_invalid_result') from exc

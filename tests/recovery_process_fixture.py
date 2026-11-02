"""Helper executable for real os._exit crash tests; no external tools or models."""
import os
from pathlib import Path
import sys

from cua_guard.recovery import RecoveryCoordinator, SQLiteRecoveryStore
from cua_guard.recovery.adapters import ManagedContextProjection
from cua_guard.recovery.contracts import RecoveryError, RecoveryRequest
from cua_guard.recovery.srr_writer import SRRWriterBackend
from test_recovery import fixture, FixtureBackend, FixtureValidator
from test_reused_recovery import Provider


def main():
    root, phase=Path(sys.argv[1]),sys.argv[2]
    def crash(at):
        if phase==at and not (root/'crashed').exists():
            os._exit(77)
    def record(name,line):
        with (root/name).open('a',encoding='utf-8') as f:
            f.write(line+'\n')
            f.flush()
            os.fsync(f.fileno())
    class Store(SQLiteRecoveryStore):
        def stage(self,*args):
            result=super().stage(*args)
            crash('stage')
            return result
        def publish(self,*args):
            result=super().publish(*args)
            crash('publish')
            return result
        def acknowledge(self,*args):
            result=super().acknowledge(*args)
            crash('acknowledge')
            return result
    class Cleaner(FixtureBackend):
        def repair(self,old,inputs,task):
            record('root-calls',old.version_id)
            return super().repair(old,inputs,task)
    class Projection(ManagedContextProjection):
        def install(self,manifest):
            result=super().install(manifest)
            record('install-calls','installed')
            crash('install')
            return result
    store=Store(root/'domain.sqlite')
    try:
        store.snapshot('tenant')
    except RecoveryError as exc:
        if exc.code!='unknown_scope': raise
        store.seed(fixture(),{'current':('summary','good'),'later':('dormant',)})
    backend=SRRWriterBackend(os.environ['ARIADNE_SRR_CHECKOUT'],Cleaner(),Provider(),{'copy':'memory_write'})
    result=RecoveryCoordinator(store,backend,FixtureValidator(),Projection(store)).recover(
        RecoveryRequest('r','tenant','Use fact',('root',),('evidence',)))
    assert result['outcome']=='ready',result['error']
    assert store.context('tenant','later')[1][0].content=='fact'
    from langgraph.checkpoint.sqlite import SqliteSaver
    from cua_guard.recovery.contracts import digest
    with SqliteSaver.from_conn_string(store.workflow_path('tenant')) as saver:
        checkpoint=saver.get_tuple({'configurable':{'thread_id':digest('r')}})
        # Last checkpoint is the completed install/ack node, not a stale task.
        assert checkpoint.checkpoint['channel_values']['job']['state']=='ready'


if __name__=='__main__':
    main()

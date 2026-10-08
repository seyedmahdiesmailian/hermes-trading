"""b239 — which ICT/SMC detectors actually reach the ENTRY decision?

smc.py has 25 detectors. The question that matters is not what exists but
what the entry decision CONSUMES. A detector that nothing reads is dead
weight and, worse, a false promise: the plan says "ICT confluence" while
the entry only ever saw 3 of the 25.

This walks the actual call graph from the entry decision backwards:
    decide_execution_action (plan.py)
      <- evaluate_monitor_cycle (orchestrator.py)
           <- strategy_signal / hermes_runtime
and reports, per detector, whether its output appears in a field the
entry decision or the executor reads.
"""
import ast, subprocess, sys, pathlib, json, collections

REPO = pathlib.Path('.')
smc = (REPO / 'engines/smc.py').read_text()
tree = ast.parse(smc)

# every public detector in smc.py
detectors = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
        detectors.append(node.name)

# where the entry decision lives and what it reads
plan_src = (REPO / 'engines/plan.py').read_text()
orch_src = (REPO / 'engines/orchestrator.py').read_text()
rt_src = (REPO / 'hermes_runtime.py').read_text()
ae_src = (REPO / 'engines/auto_executor.py').read_text()
ctx_src = (REPO / 'engines/context.py').read_text()
tm_src = (REPO / 'engines/trade_management.py').read_text()

CONSUMERS = {
    'plan.py': plan_src, 'orchestrator.py': orch_src,
    'hermes_runtime.py': rt_src, 'auto_executor.py': ae_src,
    'context.py': ctx_src, 'trade_management.py': tm_src,
}

print(f"=== {len(detectors)} public detectors in smc.py ===")
used = collections.defaultdict(list)
for d in detectors:
    for cname, src in CONSUMERS.items():
        if d in src:
            used[d].append(cname)

# smc_analyse is the aggregator — what fields does it EMIT?
print("\n=== fields smc_analyse emits ===")
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == 'smc_analyse')
emitted = set()
for n in ast.walk(fn):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        emitted.add(n.value)
    if isinstance(n, ast.Attribute) and isinstance(n.attr, str):
        emitted.add(n.attr)

# which emitted fields does the entry decision read?
plan_reads = set()
for n in ast.walk(ast.parse(plan_src)):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        plan_reads.add(n.value)
orch_reads = set()
for n in ast.walk(ast.parse(orch_src)):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        orch_reads.add(n.value)

print(f"\n=== detector -> entry-decision reachability ===")
for d in detectors:
    u = used.get(d)
    status = 'USED' if u else 'ORPHAN'
    print(f"  {status:6s} {d:32s} {u or ''}")

print("\n=== smc_analyse fields consumed by plan.py/orchestrator.py ===")
inter = sorted(emitted & (plan_reads | orch_reads))
for f in inter:
    where = [c for c in ('plan.py', 'orchestrator.py')
             if f in CONSUMERS[c]]
    print(f"  READ   {f:28s} {where}")
print(f"\n  emitted-but-unread: {len(emitted - plan_reads - orch_reads)}")

"""S004 Phase2 模块自检"""
import sys
sys.path.insert(0, 'C:/Users/17699/mozhi_platform/scripts/trading_signal')
from S004.phase2.deformation_tracker import DeformationTracker, ChannelSnapshot, DeformationScore
from S004.phase2.gray_list_manager import GrayListManager
from S004.phase2.alert_pusher import DeformationAlertPusher

print("[1/4] Imports OK")

dt = DeformationTracker()
glm = GrayListManager()
ap = DeformationAlertPusher()
print("[2/4] Instantiation OK")

old = ChannelSnapshot(
    channel_id='ch_001', date='2026-05-01',
    node_set={'A', 'B', 'C', 'D'},
    edge_list=[('A','B'), ('B','C'), ('C','D')],
    layer_structure=['1','2','3','4'],
    attributes={'trade_freq': 0.7}
)
new = ChannelSnapshot(
    channel_id='ch_001', date='2026-05-25',
    node_set={'A', 'B', 'C2', 'E'},
    edge_list=[('A','B'), ('B','C2'), ('C2','E')],
    layer_structure=['1','2','3','4'],
    attributes={'trade_freq': 0.8}
)

score = dt.detect_deformation(old, new)
assert score.flagged, "Should be flagged as deformation"
print(f"  Jaccard={score.jaccard_similarity}, GED={score.graph_edit_distance}, Composite={score.composite_score}")
print(f"  Type={score.deformation_type}")
print("[3/4] Deformation detection OK")

glm.add_channel('ch_001', '借壳通道', 'initial')
glm.escalate('ch_001', 'alert')
assert glm._gray_list['ch_001']['monitor_level'] == 'HIGH'
print(f"  Gray list: {glm.get_alert_summary()}")
print("[4/4] Gray list manager OK")

report = ap.batch_push([score])
assert report['total_pushed'] > 0
print(f"  Alert push: {report}")
print("\nAll Phase2 components verified! \u2705")

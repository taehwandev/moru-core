import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from agent_finish_gate_skip_policy import validate_required_gate_not_skipped

class FollowupWordingTests(unittest.TestCase):
    def test_later_workflow_stage_is_not_an_unfixed_gate(self):
        self.assertEqual([],validate_required_gate_not_skipped(
            'retrospective check','작업 상태는 Jira를 따르며 화면 검증은 후속 단계로 독립시켰다.',set()))

    def test_actual_followup_repairs_still_block(self):
        for evidence in ('알려진 결함에 후속 수정 필요','현재 검사의 문제에 후속 조치 필요','known issue remains','수정 필요'):
            with self.subTest(evidence=evidence):
                self.assertTrue(validate_required_gate_not_skipped('tests',evidence,set()))

if __name__=='__main__':unittest.main()

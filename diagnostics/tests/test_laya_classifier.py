"""Regression checks for automatic-comment eligibility after training post-type labels."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
import laya_classifier


class FakeAgent:
    def __init__(self, answers):
        self.answers=answers
        self.called_questions=None

    def predict(self, text, questions, **kwargs):
        self.called_questions=set(questions)
        return {"answers":{key:value for key,value in self.answers.items() if key in questions}}


class FakeAdapter:
    manifest={"minimumPostTypeConfidence":.6}

    def __init__(self, label,confidence=.9):
        self.label=label;self.confidence=confidence

    def predict(self,agent,text):
        remaining=(1-self.confidence)/3
        probabilities={label:self.confidence if label==self.label else remaining
                       for label in ("service_request","recruitment","self_promotion","other")}
        return {"choice":self.label,"answer_confidence":self.confidence,"probabilities":probabilities}


def base_answers(post_type="service_request", service_confidence=.9):
    return {"intent":{"choice":"seeking_provider","answer_confidence":.9},
            "post_type":{"choice":post_type,"answer_confidence":.9},
            "service":{"choice":"website","answer_confidence":service_confidence},
            "safety":{"choice":"A","answer_confidence":.9}}


class LayaEligibilityTests(unittest.TestCase):
    def run_classification(self, answers,adapter=None):
        agent=FakeAgent(answers)
        with patch.object(laya_classifier,"_get_agent",return_value=agent),patch.object(laya_classifier,"_post_type_adapter",adapter):
            result=laya_classifier.classify("Mẫu nội dung kiểm tra")
        return result,agent

    def test_advertisement_cannot_qualify_even_when_legacy_intent_says_seeking(self):
        result,_=self.run_classification(base_answers("self_promotion"))
        self.assertNotEqual(result["bucket"],"qualified")

    def test_recruitment_uses_trained_type_for_intent(self):
        result,agent=self.run_classification(base_answers(),FakeAdapter("recruitment"))
        self.assertEqual(result["label"],"not_seeking_provider")
        self.assertEqual(result["postType"],"recruitment")
        self.assertNotEqual(result["bucket"],"qualified")
        self.assertEqual(agent.called_questions,{"service","safety"})

    def test_low_service_confidence_keeps_request_out_of_queue(self):
        result,_=self.run_classification(base_answers(service_confidence=.4),FakeAdapter("service_request"))
        self.assertEqual(result["bucket"],"uncertain")

    def test_calibrated_type_threshold_is_respected(self):
        adapter=FakeAdapter("service_request",.7)
        adapter.manifest={"minimumPostTypeConfidence":.8}
        result,_=self.run_classification(base_answers(),adapter)
        self.assertEqual(result["bucket"],"uncertain")

    def test_safe_supported_confident_request_can_qualify(self):
        result,_=self.run_classification(base_answers(),FakeAdapter("service_request"))
        self.assertEqual(result["bucket"],"qualified")


if __name__=="__main__":unittest.main()

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

    def test_low_service_confidence_does_not_veto_supported_request(self):
        result,_=self.run_classification(base_answers(service_confidence=.4),FakeAdapter("service_request"))
        self.assertEqual(result["bucket"],"qualified")

    def test_below_70_does_not_allow_non_buyer_labels(self):
        for label in ('recruitment','self_promotion','other'):
            with self.subTest(label=label):
                result,_=self.run_classification(base_answers(),FakeAdapter(label,.65))
                self.assertNotEqual(result['bucket'],'qualified')

    def test_request_above_70_can_qualify(self):
        result,_=self.run_classification(base_answers(),FakeAdapter('service_request',.96))
        self.assertEqual(result['bucket'],'qualified')

    def test_supported_request_needing_review_can_qualify(self):
        answers=base_answers()
        answers['safety']={'choice':'review','answer_confidence':.95}
        result,_=self.run_classification(answers,FakeAdapter('service_request'))
        self.assertEqual(result['bucket'],'qualified')
        self.assertTrue(result['safetyNeedsReview'])
        self.assertEqual(result['safety'],'review')

    def test_review_label_does_not_allow_advertisements(self):
        answers=base_answers()
        answers['safety']={'choice':'review','answer_confidence':.95}
        result,_=self.run_classification(answers,FakeAdapter('self_promotion'))
        self.assertNotEqual(result['bucket'],'qualified')

    def test_unsafe_request_stays_blocked(self):
        answers=base_answers()
        answers['safety']={'choice':'B','answer_confidence':.95}
        result,_=self.run_classification(answers,FakeAdapter('service_request'))
        self.assertEqual(result['bucket'],'blocked')

    def test_calibrated_type_threshold_is_advisory_for_requests(self):
        adapter=FakeAdapter("service_request",.7)
        adapter.manifest={"minimumPostTypeConfidence":.8}
        result,_=self.run_classification(base_answers(),adapter)
        self.assertEqual(result["bucket"],"qualified")

    def test_low_safety_confidence_does_not_veto_safe_request(self):
        answers=base_answers()
        answers['safety']={'choice':'A','answer_confidence':.5}
        result,_=self.run_classification(answers,FakeAdapter('service_request',.55))
        self.assertEqual(result['bucket'],'qualified')

    def test_unsupported_service_still_cannot_qualify(self):
        answers=base_answers()
        answers['service']={'choice':'other','answer_confidence':.9}
        result,_=self.run_classification(answers,FakeAdapter('service_request'))
        self.assertNotEqual(result['bucket'],'qualified')

    def test_safe_supported_confident_request_can_qualify(self):
        result,_=self.run_classification(base_answers(),FakeAdapter("service_request"))
        self.assertEqual(result["bucket"],"qualified")


if __name__=="__main__":unittest.main()

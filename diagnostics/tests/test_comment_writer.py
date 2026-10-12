"""Provider wording checks; tests do not contact Ollama or Facebook."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app'))
import comment_writer

GOOD='DK-Tech có thể trực tiếp thiết kế website bán hàng theo yêu cầu. Bạn inbox hoặc liên hệ 0342391808 để trao đổi thêm nhé.'
BAD='DK-Tech có thể hỗ trợ bạn tìm người thiết kế website theo yêu cầu. Bạn inbox hoặc liên hệ 0342391808 để trao đổi thêm nhé.'

def response(text):
    return {'message':{'content':json.dumps({'comment':text},ensure_ascii=False)},'done_reason':'stop'}

class ProviderWordingTests(unittest.TestCase):
    def test_direct_provider_wording_is_accepted(self):
        self.assertEqual(comment_writer._parse_comment(response(GOOD)['message']['content']),GOOD)

    def test_broker_wording_is_rejected_even_with_mixed_case_and_extra_spaces(self):
        for text in (BAD,BAD.replace('tìm người','TÌM   NGƯỜI'),BAD.replace('tìm người','tìm nhà cung cấp')):
            with self.subTest(text=text),self.assertRaises(comment_writer.CommentPolicyError):
                comment_writer._parse_comment(response(text)['message']['content'])

    def test_bad_draft_is_regenerated_before_it_can_be_returned(self):
        with patch.object(comment_writer,'_request',side_effect=[response(BAD),response(GOOD)]) as request:
            result=comment_writer.generate('Mình cần tìm người làm website bán hàng')
            self.assertEqual(result['comment'],GOOD)
            self.assertEqual(request.call_count,2)

    def test_two_bad_drafts_fail_closed(self):
        with patch.object(comment_writer,'_request',side_effect=[response(BAD),response(BAD)]),self.assertRaises(comment_writer.CommentPolicyError):
            comment_writer.generate('Cần thuê làm website')

if __name__=='__main__':unittest.main()

"""생성기의 실제 읽기 요청이 새 공개 키를 apikey로만 보내는지 검사한다."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import unittest


SPEC = importlib.util.spec_from_file_location('place_builder', Path(__file__).with_name('build_place_pages.py'))
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


# 네트워크 경계만 대체하며 요청 생성과 JSON 변환은 실제 생성기를 실행한다.
class PublicKeyRequests(unittest.TestCase):
    # 실제 요청을 포착하되 키 원문은 실패 메시지에도 남기지 않는다.
    def check_request(self, operation):
        seen = []

        # HTTP 응답 본문만 최소 자료로 대체한다.
        def response(request):
            seen.append(request)
            return __import__('io').BytesIO(json.dumps([]).encode())

        with patch.object(BUILDER.urllib.request, 'urlopen', side_effect=response):
            operation()
        self.assertEqual(len(seen), 1)
        headers = {key.lower(): value for key, value in seen[0].headers.items()}
        self.assertTrue(headers.get('apikey', '').startswith('sb_publishable_'), '공개 키 종류가 다르다')
        self.assertTrue('authorization' not in headers, '공개 키를 JWT Bearer로 보내지 않는다')

    # 주간 재생성의 표 조회가 레거시 키로 되돌아가지 않는다.
    def test_table_read(self):
        self.check_request(lambda: BUILDER.fetch('/rest/v1/seoul_areas'))

    # 목록 RPC도 같은 공개 키·헤더 규칙을 사용한다.
    def test_rpc_read(self):
        self.check_request(lambda: BUILDER.rpc('list_seoul_area_status', {}))


if __name__ == '__main__':
    unittest.main()

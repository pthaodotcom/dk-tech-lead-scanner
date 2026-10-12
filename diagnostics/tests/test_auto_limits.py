"""Verify the hourly quota using an isolated database; never submit comments."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import server


class HourlyQuotaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.data_patch = patch.object(server, 'DATA_DIR', root)
        self.db_patch = patch.object(server, 'DB_PATH', root / 'scanner.sqlite3')
        self.data_patch.start()
        self.db_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.db_patch.stop)
        server.init_db()

    def add_attempts(self, db, count, *, age=timedelta(minutes=5), pending=False):
        when = (datetime.now(timezone.utc) - age).isoformat()
        first = db.execute('SELECT COUNT(*) FROM comment_queue').fetchone()[0]
        for index in range(first, first + count):
            db.execute(
                'INSERT INTO comment_queue(post_id,group_id,message,status,created_at,attempted_at) VALUES(?,?,?,?,?,?)',
                (str(index), 'sample', str(index), 'processing' if pending else 'sent',
                 when, None if pending else when))

    def configure_quota(self):
        server.save_auto_settings({'hourlyLimit': 40, 'dailyLimit': 100})

    def test_fresh_install_defaults_to_40(self):
        self.assertEqual(server.get_auto_hourly_limit(), 40)

    def test_40_can_be_saved_without_being_clamped_to_20(self):
        self.configure_quota()
        self.assertEqual(server.get_auto_hourly_limit(), 40)
        self.assertEqual(server.get_auto_daily_limit(), 100)

    def test_more_than_three_attempts_in_same_group_are_allowed(self):
        self.configure_quota()
        with server.database() as db:
            self.add_attempts(db, 4)
            server.check_auto_limits(db)

    def test_blocks_the_41st_attempt_within_a_rolling_hour(self):
        self.configure_quota()
        with server.database() as db:
            self.add_attempts(db, 39)
            server.check_auto_limits(db)
            self.add_attempts(db, 1)
            with self.assertRaisesRegex(server.AutoWait, '40 comment/giờ'):
                server.check_auto_limits(db)

    def test_expired_attempt_does_not_use_hourly_quota_but_pending_reservation_does(self):
        self.configure_quota()
        with server.database() as db:
            self.add_attempts(db, 1, age=timedelta(minutes=61))
            self.add_attempts(db, 39)
            server.check_auto_limits(db)
            self.add_attempts(db, 1, pending=True)
            with self.assertRaisesRegex(server.AutoWait, '40 comment/giờ'):
                server.check_auto_limits(db)


if __name__ == '__main__':
    unittest.main()

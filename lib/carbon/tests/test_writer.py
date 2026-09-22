import os
from unittest import TestCase

from mock import Mock, patch

from carbon.conf import settings

# carbon.writer reads storage schemas at import time, so point it at the
# test config directory before importing it.
test_directory = os.path.dirname(os.path.abspath(__file__))
settings['CONF_DIR'] = os.path.join(test_directory, 'data', 'conf-directory')
# A module-level Settings instance breaks trial's test-class scan.
del settings

import carbon.writer  # noqa:E402
from carbon.writer import TagQueue, writeTags  # noqa:E402


class TagQueueDedupTest(TestCase):
  def setUp(self):
    self.tag_queue = TagQueue(maxsize=100, update_interval=1)

  def test_add_dedupes_repeated_metric(self):
    for _ in range(10):
      self.tag_queue.add('metric.a;tag=value')
    self.assertEqual(self.tag_queue.getbatch(100), ['metric.a;tag=value'])
    self.assertEqual(self.tag_queue.getbatch(100), [])

  def test_update_dedupes_repeated_metric(self):
    for _ in range(10):
      self.tag_queue.update('metric.a;tag=value')
    self.assertEqual(self.tag_queue.getbatch(100), ['metric.a;tag=value'])
    self.assertEqual(self.tag_queue.getbatch(100), [])

  def test_add_and_update_same_metric_sent_once(self):
    self.tag_queue.add('metric.a;tag=value')
    self.tag_queue.update('metric.a;tag=value')
    self.assertEqual(self.tag_queue.getbatch(100), ['metric.a;tag=value'])

  def test_update_superseded_by_later_add(self):
    self.tag_queue.update('metric.a;tag=value')
    self.tag_queue.update('metric.b;tag=value')
    # metric.a is (re)created while its update is still pending.
    self.tag_queue.add('metric.a;tag=value')
    self.assertEqual(
      self.tag_queue.getbatch(100),
      ['metric.a;tag=value', 'metric.b;tag=value'])
    self.assertEqual(self.tag_queue.getbatch(100), [])

  def test_metric_can_be_requeued_after_drain(self):
    self.tag_queue.update('metric.a;tag=value')
    self.assertEqual(self.tag_queue.getbatch(100), ['metric.a;tag=value'])
    self.tag_queue.update('metric.a;tag=value')
    self.assertEqual(self.tag_queue.getbatch(100), ['metric.a;tag=value'])


class TagQueuePriorityTest(TestCase):
  def setUp(self):
    self.tag_queue = TagQueue(maxsize=100, update_interval=1)

  def test_adds_drained_before_updates(self):
    self.tag_queue.update('metric.u1;tag=value')
    self.tag_queue.update('metric.u2;tag=value')
    self.tag_queue.add('metric.a1;tag=value')
    self.tag_queue.add('metric.a2;tag=value')
    self.assertEqual(
      self.tag_queue.getbatch(100),
      ['metric.a1;tag=value', 'metric.a2;tag=value',
       'metric.u1;tag=value', 'metric.u2;tag=value'])

  def test_batch_boundary_prefers_adds(self):
    self.tag_queue.update('metric.u1;tag=value')
    self.tag_queue.add('metric.a1;tag=value')
    self.tag_queue.add('metric.a2;tag=value')
    # A small batch must be filled by pending adds first.
    self.assertEqual(
      self.tag_queue.getbatch(2), ['metric.a1;tag=value', 'metric.a2;tag=value'])
    self.assertEqual(self.tag_queue.getbatch(2), ['metric.u1;tag=value'])
    self.assertEqual(self.tag_queue.getbatch(2), [])


class TagQueueUpdateIntervalTest(TestCase):
  def test_update_interval_throttles_updates(self):
    tag_queue = TagQueue(maxsize=100, update_interval=3)
    for i in range(9):
      tag_queue.update('metric.%d;tag=value' % i)
    # Only the 1st, 4th and 7th update() calls are queued.
    self.assertEqual(
      tag_queue.getbatch(100),
      ['metric.0;tag=value', 'metric.3;tag=value', 'metric.6;tag=value'])

  def test_update_interval_one_queues_every_update(self):
    tag_queue = TagQueue(maxsize=100, update_interval=1)
    for i in range(3):
      tag_queue.update('metric.%d;tag=value' % i)
    self.assertEqual(
      tag_queue.getbatch(100),
      ['metric.0;tag=value', 'metric.1;tag=value', 'metric.2;tag=value'])

  def test_update_interval_counts_calls_not_metrics(self):
    tag_queue = TagQueue(maxsize=100, update_interval=2)
    # Hot metric written repeatedly: only every 2nd call is considered,
    # and dedup collapses the queued ones until drained.
    for _ in range(8):
      tag_queue.update('hot.metric;tag=value')
    self.assertEqual(tag_queue.getbatch(100), ['hot.metric;tag=value'])


class TagQueuePressureTest(TestCase):
  def test_add_queue_is_bounded(self):
    tag_queue = TagQueue(maxsize=2, update_interval=1)
    for i in range(10):
      tag_queue.add('metric.%d;tag=value' % i)
    batch = tag_queue.getbatch(100)
    self.assertEqual(batch, ['metric.0;tag=value', 'metric.1;tag=value'])
    self.assertEqual(tag_queue.getbatch(100), [])

  def test_update_queue_is_bounded(self):
    tag_queue = TagQueue(maxsize=2, update_interval=1)
    for i in range(10):
      tag_queue.update('metric.%d;tag=value' % i)
    batch = tag_queue.getbatch(100)
    self.assertEqual(batch, ['metric.0;tag=value', 'metric.1;tag=value'])
    self.assertEqual(tag_queue.getbatch(100), [])

  def test_dedup_relieves_queue_pressure(self):
    tag_queue = TagQueue(maxsize=2, update_interval=1)
    # Far more updates than the queue bound, but only 2 distinct metrics.
    for _ in range(100):
      tag_queue.update('metric.a;tag=value')
      tag_queue.update('metric.b;tag=value')
    self.assertEqual(
      tag_queue.getbatch(100),
      ['metric.a;tag=value', 'metric.b;tag=value'])

  def test_full_queue_still_dedupes_after_drain(self):
    tag_queue = TagQueue(maxsize=1, update_interval=1)
    tag_queue.add('metric.a;tag=value')
    tag_queue.add('metric.b;tag=value')  # dropped, queue is full
    self.assertEqual(tag_queue.getbatch(100), ['metric.a;tag=value'])
    # After draining, new adds are accepted again.
    tag_queue.add('metric.b;tag=value')
    self.assertEqual(tag_queue.getbatch(100), ['metric.b;tag=value'])


class WriteTagsTest(TestCase):
  def setUp(self):
    self.database_mock = Mock()
    database_patch = patch.object(
      carbon.writer.state, 'database', self.database_mock)
    database_patch.start()
    self.addCleanup(database_patch.stop)
    settings_patch = patch.dict('carbon.conf.settings', {'TAG_BATCH_SIZE': 2})
    settings_patch.start()
    self.addCleanup(settings_patch.stop)
    self.tag_queue = TagQueue(maxsize=100, update_interval=1)
    queue_patch = patch.object(carbon.writer, 'tagQueue', self.tag_queue)
    queue_patch.start()
    self.addCleanup(queue_patch.stop)

  def test_write_tags_sends_deduped_batches(self):
    for _ in range(5):
      self.tag_queue.add('metric.a;tag=value')
    self.tag_queue.add('metric.b;tag=value')
    writeTags()
    self.database_mock.tag.assert_called_once_with(
      'metric.a;tag=value', 'metric.b;tag=value')

  def test_write_tags_drains_multiple_batches(self):
    for i in range(5):
      self.tag_queue.update('metric.%d;tag=value' % i)
    writeTags()
    self.assertEqual(
      self.database_mock.tag.call_args_list,
      [
        (('metric.0;tag=value', 'metric.1;tag=value'),),
        (('metric.2;tag=value', 'metric.3;tag=value'),),
        (('metric.4;tag=value',),),
      ])

  def test_write_tags_empty_queue(self):
    writeTags()
    self.database_mock.tag.assert_not_called()

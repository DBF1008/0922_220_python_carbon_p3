import os
from unittest import TestCase

from mock import call, patch


CONF_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data', 'conf-directory')


def load_writer():
  from carbon.conf import settings
  settings.setdefault('CONF_DIR', CONF_DIRECTORY)
  import carbon.writer as writer
  return writer


class TagQueueTest(TestCase):

  def setUp(self):
    self.TagQueue = load_writer().TagQueue

  def test_duplicate_adds_are_deduplicated(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.add('metric.a;tag=value')
    tag_queue.add('metric.a;tag=value')

    self.assertEqual(['metric.a;tag=value'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_duplicate_updates_are_deduplicated(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.update('metric.a;tag=value')
    tag_queue.update('metric.a;tag=value')

    self.assertEqual(['metric.a;tag=value'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_update_interval_remains_global(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=3)

    tag_queue.update('metric.a')
    tag_queue.update('metric.b')
    tag_queue.update('metric.c')
    tag_queue.update('metric.d')

    self.assertEqual(['metric.a', 'metric.d'], tag_queue.getbatch(10))

  def test_repeated_updates_do_not_fill_the_queue(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    for _ in range(100):
      tag_queue.update('metric.a')

    self.assertEqual(['metric.a'], tag_queue.getbatch(10))

  def test_adds_are_sent_before_updates(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.add('metric.a')
    tag_queue.update('metric.b')
    tag_queue.add('metric.c')

    self.assertEqual(['metric.a', 'metric.c'], tag_queue.getbatch(2))
    self.assertEqual(['metric.b'], tag_queue.getbatch(2))

  def test_add_promotes_a_pending_update(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.update('metric.a')
    tag_queue.add('metric.a')

    self.assertEqual(['metric.a'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_update_is_merged_with_a_pending_add(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.add('metric.a')
    tag_queue.update('metric.a')

    self.assertEqual(['metric.a'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_full_queue_evicts_updates_for_adds(self):
    tag_queue = self.TagQueue(maxsize=2, update_interval=1)

    tag_queue.update('metric.a')
    tag_queue.update('metric.b')
    tag_queue.add('metric.c')

    self.assertEqual(['metric.c', 'metric.b'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_full_queue_drops_new_items_without_limiting_priority(self):
    tag_queue = self.TagQueue(maxsize=2, update_interval=1)

    tag_queue.add('metric.a')
    tag_queue.add('metric.b')
    tag_queue.add('metric.c')
    tag_queue.update('metric.d')

    self.assertEqual(['metric.a', 'metric.b'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_full_queue_drops_updates(self):
    tag_queue = self.TagQueue(maxsize=2, update_interval=1)

    tag_queue.update('metric.a')
    tag_queue.update('metric.b')
    tag_queue.update('metric.c')

    self.assertEqual(['metric.a', 'metric.b'], tag_queue.getbatch(10))
    self.assertEqual([], tag_queue.getbatch(10))

  def test_batches_are_limited_and_preserve_priority_across_boundaries(self):
    tag_queue = self.TagQueue(maxsize=10, update_interval=1)

    tag_queue.add('metric.a')
    tag_queue.update('metric.b')
    tag_queue.add('metric.c')
    tag_queue.update('metric.d')

    self.assertEqual(['metric.a'], tag_queue.getbatch())
    self.assertEqual(['metric.c'], tag_queue.getbatch(1))
    self.assertEqual(['metric.b', 'metric.d'], tag_queue.getbatch(2))
    self.assertEqual([], tag_queue.getbatch(2))


class WriteTagsTest(TestCase):

  def test_write_tags_uses_configured_batch_boundaries(self):
    writeTags = load_writer().writeTags
    batches = [
      ['metric.a', 'metric.b'],
      ['metric.c'],
      []
    ]

    with patch('carbon.writer.tagQueue') as tag_queue, \
        patch('carbon.state.database') as database, \
        patch.dict('carbon.writer.settings', {'TAG_BATCH_SIZE': 2}):
      tag_queue.getbatch.side_effect = batches

      writeTags()

    self.assertEqual(
      [call(2), call(2), call(2)],
      tag_queue.getbatch.call_args_list
    )
    database.tag.assert_has_calls([
      call('metric.a', 'metric.b'),
      call('metric.c')
    ])
    self.assertEqual(2, database.tag.call_count)

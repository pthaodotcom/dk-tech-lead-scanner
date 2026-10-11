import assert from 'node:assert/strict';
import test from 'node:test';

await import('../facebook-request-probe/core.js');
const core = globalThis.__DKTECH_PROBE_CORE__;

test('keeps text from the richest streamed Story occurrence', () => {
  const first = {
    data: {node: {group_feed: {
      edges: [{node: {
        __typename: 'Story', post_id: 'post-1',
        comet_sections: {content: {story: {message: {text: 'Cần thiết kế website doanh nghiệp'}}}},
      }}, {
        node: {__typename: 'CommentComposerGroupMentionsPlugin', id: 'plugin-1'},
      }],
      page_info: {has_next_page: true, end_cursor: 'cursor-1'},
    }}},
  };
  const streamedDuplicate = {
    label: 'GroupsCometFeedRegularStoriesPaginationQuery$defer$group_feed',
    data: {node: {__typename: 'Story', post_id: 'post-1'}},
  };
  const body = `${JSON.stringify(first)}\n${JSON.stringify(streamedDuplicate)}`;
  const summary = core.summarizeResponse(body, 'group_posts', 'GroupsCometFeedRegularStoriesPaginationQuery');

  assert.equal(summary.itemCount, 1);
  assert.equal(summary.items[0].id, 'post-1');
  assert.equal(summary.items[0].hasText, true);
  assert.equal(summary.items[0].text, 'Cần thiết kế website doanh nghiệp');
  assert.equal(summary.items[0].occurrences, 2);
  assert.equal(summary.hasNextPage, true);
  assert.equal(summary.endCursor, 'cursor-1');
});

test('extracts alternate Facebook message paths', () => {
  const story = {
    comet_sections: {content: {story: {comet_sections: {message_container: {
      story: {message: {text: 'Nội dung ở message_container'}},
    }}}}},
  };
  assert.equal(core.extractStoryText(story), 'Nội dung ở message_container');
});

test('recognizes current joined-group query names and true Group nodes', () => {
  assert.equal(core.queryKind('GroupsCometJoinsRootQuery'), 'joined_groups');
  assert.equal(core.queryKind('GroupsCometAllJoinedGroupsSectionPaginationQuery'), 'joined_groups');
  const body = JSON.stringify({data: {viewer: {tab_groups_list: {
    edges: [
      {node: {__typename: 'Group', id: '1', name: 'Nhóm 1'}},
      {node: {__typename: 'Story', id: 'not-a-group'}},
    ],
    page_info: {has_next_page: false, end_cursor: 'done'},
  }}}});
  const summary = core.summarizeResponse(body, 'joined_groups', 'GroupsCometAllJoinedGroupsSectionPaginationQuery');
  assert.equal(summary.itemCount, 1);
  assert.equal(summary.items[0].name, 'Nhóm 1');
  assert.equal(summary.hasNextPage, false);
});

test('detects a renamed group feed query by response structure', () => {
  const body = JSON.stringify({data: {node: {group_feed: {edges: [{node: {
    __typename: 'Story', post_id: 'post-2', message: {text: 'Có nội dung'},
  }}]}}}});
  assert.deepEqual(core.classifyResponse(body, 'GroupsCometRenamedTimelineQuery'), {
    kind: 'group_posts', source: 'structure',
  });
  assert.deepEqual(core.classifyResponse(body, 'GroupsCometFeedRegularStoriesPaginationQuery'), {
    kind: 'group_posts', source: 'name', structuralKind: 'group_posts',
  });
});

test('replaces only exact group IDs in nested variables', () => {
  const source = {id: '111', youthIntegrityHostID: '111', nested: ['111', 'x111'], untouched: 111};
  assert.deepEqual(core.replaceExact(source, '111', '222'), {
    id: '222', youthIntegrityHostID: '222', nested: ['222', 'x111'], untouched: 111,
  });
});

test('ignores the end-of-feed sentinel query', () => {
  assert.equal(core.queryKind('GroupsCometEndOfFeedQuery'), null);
});

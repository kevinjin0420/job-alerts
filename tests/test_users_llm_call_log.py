from __future__ import annotations

import unittest
from unittest.mock import patch

import users


class ListLlmCallsQueryTests(unittest.TestCase):
    """Regression test: DynamoDB rejected "shard" as a bare KeyConditionExpression
    attribute name ("Attribute name is a reserved keyword") until aliased via
    ExpressionAttributeNames - broke every /api/llm-logs request in production."""

    def test_query_aliases_the_reserved_shard_attribute_name(self) -> None:
        with patch.object(users._dynamodb, "query", return_value={"Items": []}) as mock_query:
            users.list_llm_calls(None, 50)

        kwargs = mock_query.call_args.kwargs
        self.assertNotIn("shard", kwargs["KeyConditionExpression"].replace("#shard", ""))
        self.assertEqual(kwargs["ExpressionAttributeNames"], {"#shard": "shard"})

    def test_before_cursor_used_as_exclusive_start_key(self) -> None:
        with patch.object(users._dynamodb, "query", return_value={"Items": []}) as mock_query:
            users.list_llm_calls("0000000000123#abcd1234", 50)

        kwargs = mock_query.call_args.kwargs
        self.assertEqual(
            kwargs["ExclusiveStartKey"], {"shard": {"S": "llm"}, "sort_key": {"S": "0000000000123#abcd1234"}}
        )

    def test_last_evaluated_key_becomes_next_cursor(self) -> None:
        response = {
            "Items": [],
            "LastEvaluatedKey": {"shard": {"S": "llm"}, "sort_key": {"S": "0000000000456#efgh5678"}},
        }
        with patch.object(users._dynamodb, "query", return_value=response):
            _, next_cursor = users.list_llm_calls(None, 50)

        self.assertEqual(next_cursor, "0000000000456#efgh5678")

    def test_no_last_evaluated_key_means_no_next_cursor(self) -> None:
        with patch.object(users._dynamodb, "query", return_value={"Items": []}):
            _, next_cursor = users.list_llm_calls(None, 50)

        self.assertIsNone(next_cursor)

    def test_event_filter_adds_filter_expression(self) -> None:
        with patch.object(users._dynamodb, "query", return_value={"Items": []}) as mock_query:
            users.list_llm_calls(None, 50, event_filter="validity_check")

        kwargs = mock_query.call_args.kwargs
        self.assertEqual(kwargs["FilterExpression"], "#event = :event")
        self.assertEqual(kwargs["ExpressionAttributeNames"]["#event"], "event")
        self.assertEqual(kwargs["ExpressionAttributeValues"][":event"], {"S": "validity_check"})

    def test_no_event_filter_omits_filter_expression(self) -> None:
        with patch.object(users._dynamodb, "query", return_value={"Items": []}) as mock_query:
            users.list_llm_calls(None, 50)

        self.assertNotIn("FilterExpression", mock_query.call_args.kwargs)


class RecordLlmCallTests(unittest.TestCase):
    def test_writes_item_with_shard_and_sort_key(self) -> None:
        with patch.object(users._dynamodb, "put_item") as mock_put:
            users.record_llm_call(event="classifier_call", model="fake-model", reason="ok")

        item = mock_put.call_args.kwargs["Item"]
        self.assertEqual(item["shard"]["S"], "llm")
        self.assertIn("#", item["sort_key"]["S"])
        self.assertEqual(item["event"]["S"], "classifier_call")

    def test_none_fields_are_omitted_not_written_as_null(self) -> None:
        with patch.object(users._dynamodb, "put_item") as mock_put:
            users.record_llm_call(event="validity_check", user_id=None, fit_score=None)

        item = mock_put.call_args.kwargs["Item"]
        self.assertNotIn("user_id", item)
        self.assertNotIn("fit_score", item)


if __name__ == "__main__":
    unittest.main()

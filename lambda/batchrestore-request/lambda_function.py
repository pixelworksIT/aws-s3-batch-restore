## #!/usr/bin/env python3
##
# Copyright 2019 Pixelworks Inc.
#
# Author: Houyu Li <hyli@pixelworks.com>
#
# Making restore request to specific S3 bucket and prefix
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# 		http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
## // ##

import os, json, datetime, time, base64, re
import boto3

from hashlib import sha1, sha256

def lambda_handler(event, context):
    # Necessary vars
    bucket = None
    prefix = None
    watchers = None

    if u'bucket' in event:
        bucket = event[u'bucket'].strip()
    if u'prefix' in event:
        prefix = event[u'prefix'].strip()
    if u'watchers' in event:
        watchers = event[u'watchers'].strip()

    if not bucket:
        return _ret(500, u'Missing param: bucket')
    if not prefix:
        # We allow empty prefix
        prefix = u''

    # The AWS session
    aws_sess = boto3.session.Session(
        region_name = os.environ[u'AWS_REGION'],
        aws_access_key_id = os.environ[u'AWS_ACCESS_KEY_ID'],
        aws_secret_access_key = os.environ[u'AWS_SECRET_ACCESS_KEY'],
        aws_session_token = os.environ[u'AWS_SESSION_TOKEN']
    )

    # The S3 client
    s3_client = aws_sess.client(u's3')
    # The S3 resource
    s3_resource = aws_sess.resource(u's3')
    # Event client
    evt_client = aws_sess.client(u'events')
    # Lambda client
    lbd_client = aws_sess.client(u'lambda')
    # DynamoDb tables
    tbl_app_config = aws_sess.resource(u'dynamodb').Table(u'AppConfig')
    tbl_batch_restore_batch = aws_sess.resource(u'dynamodb').Table(u'BatchRestoreBatch')
    tbl_batch_restore_objects = aws_sess.resource(u'dynamodb').Table(u'BatchRestoreObjects')

    # Try to create a record first
    batch_id = None
    try:
        # Make sure we handle watchers properly
        default_watchers = _get_appconfig(tbl_app_config, u'batch-restore-watchers')
        if watchers:
            watchers = u','.join([watchers, default_watchers])
        else:
            watchers = default_watchers

        batch_id = _add_batch_restore(
            tbl_batch_restore_batch,
            bucket,
            prefix,
            watchers
        )
    except:
        return _ret(
            500,
            u"Failed to create restore for path s3://%s/%s" % (bucket, prefix)
        )

    res_objs = None
    try:
        # Now list all objects in the given bucket and prefix
        res_objs = s3_client.list_objects_v2(
            Bucket = bucket,
            Prefix = prefix
        )
    except:
        _del_batch_restore(tbl_batch_restore_batch, batch_id)
        return _ret(
            500,
            u"Failed to list objects in path s3://%s/%s" % (bucket, prefix)
        )

    if res_objs[u'KeyCount'] > 0:
        # There are some objects
        n_objs = 0

        for obj in res_objs[u'Contents']:
            # We skip "directory" objects
            if re.compile(r'\/$').findall(obj[u'Key']):
                continue
            # Count for object in GLACIER
            if obj[u'StorageClass'] == u'GLACIER' or obj[u'StorageClass'] == u'DEEP_ARCHIVE':
                # Push the record to table BatchRestoreObjects
                _batch_restore_push(tbl_batch_restore_objects, batch_id, bucket, obj[u'Key'])
                # Add 1 to number of objects
                n_objs += 1

        if n_objs > 0:
            rule_name = u'brm-%s' % (sha1(batch_id.encode()).hexdigest())
            monitor_func_arn = _get_appconfig(tbl_app_config, u'batch-restore-monitor-func')
            monitor_func = monitor_func_arn.split(u':')[-1]
            # Create event rule for monitoring
            try:
                # Try to remove permission from Lambda function first in anyway
                lbd_client.remove_permission(
                    FunctionName = monitor_func,
                    StatementId = rule_name
                )
                # Create the rule
                res_rule = evt_client.put_rule(
                    Name = rule_name,
                    ScheduleExpression = u'rate(30 minutes)'
                )
                # Allow invoke from EventBridge
                lbd_client.add_permission(
                    FunctionName = monitor_func,
                    StatementId = rule_name,
                    Action = u'lambda:InvokeFunction',
                    Principal = u'events.amazonaws.com',
                    SourceArn = res_rule[u'RuleArn']
                )
                # Create target for the rule
                evt_client.put_targets(
                    Rule = rule_name,
                    Targets = [{
                        u'Id': rule_name,
                        u'Arn': monitor_func_arn,
                        u'Input': u'{"batchId":"%s"}' % (batch_id)
                    }]
                )
            except:
                rule_name = u''
                print(u"Restore requests sent, but failed to create the monitor.")

            # Find objects in GLACIER and restore requests sent
            ret_data = _ret(
                200,
                u"Restore requests sent for %d objects" % (n_objs)
            )
            ret_data[u'body'][u'restoreCount'] = n_objs
            ret_data[u'body'][u'batchId'] = batch_id
            ret_data[u'body'][u'restoreMonitor'] = rule_name
            return ret_data
        else:
            # No object in GLACIER
            _del_batch_restore(tbl_batch_restore_batch, batch_id)
            return _ret(
                404,
                u"No restorable object in path s3://%s/%s" % (bucket, prefix)
            )
    else:
        # No object in giving bucket and prefix
        # Nothing to restore
        _del_batch_restore(tbl_batch_restore_batch, batch_id)
        return _ret(
            404,
            u"Nothing can be restored in path s3://%s/%s" % (bucket, prefix)
        )

def _ret(code, message):
    return {
        u'statusCode': code,
        u'body': {
            u'message': message
        }
    }

def _batch_restore_push(table, batch_id, bucket, key):
    item_id = _generate_batch_id(bucket, key)

    table.put_item(
        Item = {
            u'id': item_id,
            u'bucket': bucket,
            u'key': key,
            u'batchId': batch_id
        }
    )

def _add_batch_restore(table, bucket, prefix, watchers = None):
    batch_id = _generate_batch_id(bucket, prefix)

    data = {
        u'batchId': batch_id,
        u'bucket': bucket,
        u'prefix': prefix
    }
    if watchers:
        data[u'watchers'] = watchers

    table.put_item(
        Item = data
    )

    return batch_id

def _del_batch_restore(table, batch_id):
    table.delete_item(
        Key = {u'batchId' : batch_id}
    )

def _generate_batch_id(bucket, prefix):
    data = u'bk=%s;pr=%s' % (
        base64.b64encode(bucket.encode()).decode(),
        base64.b64encode(prefix.encode()).decode()
    )

    return sha256(data.encode()).hexdigest()

def _ret(code, message):
    return {
        u'statusCode': code,
        u'body': {
            u'message': message
        }
    }

def _get_appconfig(table, conf_key):
    return table.get_item(
        Key = {
            u'confKey': conf_key
        },
        ConsistentRead = True
    )[u'Item'][u'confValue']

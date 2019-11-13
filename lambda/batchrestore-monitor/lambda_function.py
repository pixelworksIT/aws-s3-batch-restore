## #!/usr/bin/env python3
##
# Copyright 2019 Pixelworks Inc.
#
# Author: Houyu Li <hyli@pixelworks.com>
#
# Check restore status of each object in a specific request.
# Send restore finish notification E-mail if all Done.
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

import os, json, re, datetime
import boto3
import smtplib

from botocore.client import Config
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from hashlib import sha1

def lambda_handler(event, context):
    if u'batchId' not in event:
        return _ret(200, u"No input. Return success anyway.")

    # The AWS session
    aws_sess = boto3.session.Session(
        region_name = os.environ[u'AWS_REGION'],
        aws_access_key_id = os.environ[u'AWS_ACCESS_KEY_ID'],
        aws_secret_access_key = os.environ[u'AWS_SECRET_ACCESS_KEY'],
        aws_session_token = os.environ[u'AWS_SESSION_TOKEN']
    )

    # The S3 client
    s3_client = aws_sess.client(
        u's3',
        config = Config(
            signature_version = u's3v4'
        )
    )
    # Event client
    evt_client = aws_sess.client(u'events')
    # DynamoDb tables
    tbl_app_config = aws_sess.resource(u'dynamodb').Table(u'AppConfig')
    tbl_batch_restore_batch = aws_sess.resource(u'dynamodb').Table(u'BatchRestoreBatch')
    tbl_batch_restore_objects = aws_sess.resource(u'dynamodb').Table(u'BatchRestoreObjects')

    # Number of unfinished object restore
    n_unfinished = 0

    # Search for the batch restore objects
    batch_id = event[u'batchId']

    batch_info = {}
    res_objs = {}
    try:
        # Get batch restore request information
        batch_info = tbl_batch_restore_batch.get_item(
            Key = {
                u'batchId': batch_id
            },
            ConsistentRead = True
        )[u'Item']

        # Get all objects
        res_objs = tbl_batch_restore_objects.query(
            IndexName = u'batchId-index',
            KeyConditions = {
                u'batchId' : {
                    u'AttributeValueList' : [
                        batch_id
                    ],
                    u'ComparisonOperator' : u'EQ'
                }
            }
        )
    except:
        # Query error. Set 0 to Count
        res_objs[u'Count'] = 0

    if res_objs[u'Count'] > 0:
        # We found these objects
        # Then we check status and update status in table
        for obj in res_objs[u'Items']:
            # Request object info header
            obj_head_info = s3_client.head_object(
                Bucket = obj[u'bucket'],
                Key = obj[u'key']
            )

            # By default we think the restore process is ongoing
            obj_restore_state = u'Ongoing'
            obj_exp_timestamp = 0

            # Parse the Restore head
            for restore_header in re.findall(r'([^=\s,]+)=((["\'])[^"\']+?\3)', obj_head_info[u'Restore']):
                if restore_header[0].lower() == u'ongoing-request' and restore_header[1].lower() == u'"false"':
                    # The object is already restored
                    obj_restore_state = u'Done'
                if restore_header[0].lower() == u'ongoing-request' and restore_header[1].lower() == u'"true"':
                    # The object is being restored
                    n_unfinished += 1
                if restore_header[0].lower() == u'expiry-date':
                    # Set expire time if applicable
                    obj_exp_timestamp = int(
                        datetime.datetime.timestamp(
                            datetime.datetime.strptime(
                                restore_header[1].strip(u'"'),
                                u'%a, %d %b %Y %X %Z'
                            )
                        )
                    )

            # Update object status in table
            try:
                # We will check the state when update. So we need to make sure state is there
                # If not, give it an empty value
                if u'state' not in obj:
                    obj[u'state'] = u''
                # We only update on state change
                if obj_restore_state != obj[u'state']:
                    tbl_batch_restore_objects.update_item(
                        Key = {
                            u'id': obj[u'id']
                        },
                        AttributeUpdates = {
                            u'state': {
                                u'Value': obj_restore_state,
                                u'Action': u'PUT'
                            },
                            u'expire': {
                                u'Value': obj_exp_timestamp,
                                u'Action': u'PUT'
                            }
                        }
                    )
            except:
                # Don't block on any error. Log and go on.
                print(u"Update state failed: s3://%s/%s" % (obj[u'bucket'], obj[u'key']))

        # If unfinished = 0, we send notification and delete data from database
        if n_unfinished == 0:
            print(u"All restore is done. %s" % (batch_id))
            # Send mail
            _send_mail_all_done(batch_info, tbl_app_config)
            # Remove event
            rule_name = u'brm-%s' % (sha1(batch_id.encode()).hexdigest())
            try:
                evt_client.remove_targets(
                    Rule = rule_name,
                    Ids = [ rule_name ],
                    Force = True
                )
                evt_client.delete_rule(
                    Name = rule_name,
                    Force = True
                )
            except:
                # Some error. Need manual remove
                print(u"Remove monitor rule failed. Need manually remove. %s" % (batch_id))
            # Delete data
            # Delete objects first
            try:
                for obj in res_objs[u'Items']:
                    tbl_batch_restore_objects.delete_item(
                        Key = {
                            u'id': obj[u'id']
                        }
                    )
                # Delete request information
                tbl_batch_restore_batch.delete_item(
                    Key = {
                        u'batchId': batch_id
                    }
                )
            except:
                # Some error. Need manual remove
                print(u"Clean data failed. Need manually remove. %s" % (batch_id))

            print(u"Data cleaned. %s" % (batch_id))
        else:
            # Not finished yet
            print(u"Restore not finished. %s" % (batch_id))

    else:
        # Not found any object?
        return _ret(200, u"No object in provided request %s" % (batch_id))

    return _ret(200, u"Return success anyway.")

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

def _send_mail_all_done(batch_restore_info, tbl_app_config):
    # If no watchers defined in batch restore info, just return
    if u'watchers' not in batch_restore_info:
        print(u"No watchers, not sending any e-mail. %s" % (batch_restore_info[u'batchId']))
        return
    if not batch_restore_info[u'watchers'].strip():
        print(u"No watchers, not sending any e-mail. %s" % (batch_restore_info[u'batchId']))
        return

    ## Get SMTP endpoint and access info
    smtp_server = _get_appconfig(tbl_app_config, u'ses-smtp-server')
    smtp_port = _get_appconfig(tbl_app_config, u'ses-smtp-port')
    smtp_user = _get_appconfig(tbl_app_config, u'ses-smtp-user')
    smtp_pass = _get_appconfig(tbl_app_config, u'ses-smtp-pass')

    ## Prepare mail
    mail_subject = u'Pixelworks S3 Restore Finished'
    mail_from = u'noreply@aws.pixelworks.com'
    mail_to = batch_restore_info[u'watchers'].strip()

    msg = MIMEMultipart(u'mixed')

    msg[u'Subject'] = mail_subject
    msg[u'From'] = mail_from
    msg[u'To'] = mail_to

    msg_html = u"<h3>Hello, Sir,</h3>"
    msg_html += u"<p>Requests for restoring objects from archive on following S3 path is done.<br>"
    msg_html += u"s3://%s/%s" % (batch_restore_info[u'bucket'], batch_restore_info[u'prefix'])
    msg_html += u"</p>"

    html_part = MIMEText(msg_html.encode(u'utf-8'), u'html', u'utf-8')

    msg_body = MIMEMultipart(u'alternative')
    msg_body.attach(html_part)

    msg.attach(msg_body)

    # Using SMTP to send mail
    ses_smtp = smtplib.SMTP(smtp_server, int(smtp_port))
    ses_smtp.starttls()
    ses_smtp.login(smtp_user, smtp_pass)
    ses_smtp.sendmail(mail_from, mail_to.split(u','), msg.as_string())
    ses_smtp.quit()

    print(u"Mail sent. %s" % (batch_restore_info[u'batchId']))

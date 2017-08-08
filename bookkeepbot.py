import boto3
import json
import logging
import re
import os

from base64 import b64decode
from urlparse import parse_qs
from decimal import Decimal
from urllib2 import Request, urlopen, URLError, HTTPError

table_name = os.environ['TABLE_NAME']
region_name = os.getenv('REGION_NAME', 'ap-northeast-2')

logger = logging.getLogger()
logger.setLevel(logging.INFO)
dynamo = boto3.client('dynamodb', region_name=region_name)

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': err.message if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
        },
    }


def parse_user_and_amount(text):
    user = None

    p_user = re.match(r"<\@(.*)\|(.*)>", text)
    if p_user:
        user = p_user.group(2)

    amount = None
    p_amount = re.match(r"(.*)(-?)(\$)(\d\d?(\d+|(,\d\d\d)*)(\.\d+)?|(\.\d+))", text)
    if p_amount:
        amount = Decimal(p_amount.group(4).replace(',', '').replace('$', ''))

    return user,amount


def save_to_db(user, owed_user, owed_amount):
    # subtract owed_amount from user
    dynamo.update_item(TableName=table_name,
        Key={'username':{'S':user}},
        AttributeUpdates= {
            'chips':{
                'Action': 'ADD',
                'Value': {'N': str(-owed_amount)}
            }
        }
    )

    #add owed_amount to owed_user
    dynamo.update_item(TableName=table_name,
        Key={'username': {'S':owed_user}},
        AttributeUpdates= {
            'chips':{
                'Action': 'ADD',
                'Value': {'N': str(owed_amount)}
            }
        }
    )


def get_tally():
    res = dynamo.scan(TableName=table_name)

    logger.info(res)

    tally_dict = {}
    for item in res['Items']:
        tally_dict[item['username']['S']] = item['chips']['N']

    tally_msg = "```"
    for user, chips in sorted(tally_dict.items()):
        tally_msg += "{:<10}:{:>5}\n".format(user, chips)
    tally_msg += "```"
    return tally_msg


def lambda_handler(event, context):
    # keep alive ping will keep the lambda warm
    if 'keep_alive_ping' in event:
        logger.info("ping")
        return

    params = parse_qs(event['body'])
    token = params['token'][0]

    user = params['user_name'][0]
    command = params['command'][0]
    channel = params['channel_name'][0]
    command_text = params['text'][0]
    response_url = params['response_url'][0]

    owed_user, owed_amount = parse_user_and_amount(command_text)

    if command_text == 'list' or command_text == 'tally':
        response_msg = get_tally()
    elif owed_user is None:
        response_msg = "Make sure to include a user who is a member of the team, or use `list` to get the current chip count"
    elif owed_amount is None:
        response_msg = "Make sure to include an amount, or use `list` to get the current chip count"
    elif owed_amount < Decimal(0):
        response_msg = "You can't owe someone negative. Get them to owe you to erase debts."
    elif owed_user == user:
        response_msg = "You can resolve your own debts to yourself. No chips changed!"
    else:
        save_to_db(user, owed_user, owed_amount)
        response_msg = "success! @%s lost %s chips while @%s gained %s chips" % (user, owed_amount, owed_user, owed_amount)
        logger.info(response_msg)


    return respond(None, {
            'response_type': 'in_channel',
            'text': response_msg
        })

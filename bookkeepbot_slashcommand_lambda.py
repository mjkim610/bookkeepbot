import boto3
import json
import logging
import re
import os

from urlparse import parse_qs
from decimal import Decimal

table_name = os.environ['TABLE_NAME']  # for example: bookkeepbot_ledger
region_name = os.getenv('REGION_NAME', 'ap-northeast-2')  # for example: ap-northeast-2

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


def parse_user_and_amount(text):  # make sure to check `Escape channels, users, and links sent to your app` in Slack
    lender = None

    p_lender = re.match(r"(<\@(.*)\|(.*)>)", text)
    if p_lender:
        lender = p_lender.group(1)

    amount = None
    p_amount = re.match(r"(.*)(-?)(\$)(\d\d?(\d+|(,\d\d\d)*)(\.\d+)?|(\.\d+))", text)
    if p_amount:
        amount = Decimal(p_amount.group(4).replace(',', '').replace('$', ''))

    return lender, amount


def save_to_db(debtor, lender, amount):  # make sure to use the same keys in DynamoDB
    # subtract amount from debtor
    dynamo.update_item(TableName=table_name,
                       Key={'user':{'S': debtor}},
                       AttributeUpdates={
                           'chips': {
                               'Action': 'ADD',
                               'Value': {'N': str(-amount)}
                           }
                       }
    )

    # add amount to lender
    dynamo.update_item(TableName=table_name,
                       Key={'user': {'S': lender}},
                       AttributeUpdates={
                           'chips': {
                               'Action': 'ADD',
                               'Value': {'N': str(amount)}
                           }
                       }
    )


def get_tally():
    res = dynamo.scan(TableName=table_name)

    logger.info(res)

    tally_dict = {}
    for item in res['Items']:
        tally_dict[item['user']['S']] = item['chips']['N']

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
    user_id = params['user_id'][0]
    user_name = params['user_name'][0]
    debtor = "<@" + user_id + "|" + user_name + ">"
    command_text = params['text'][0]

    lender, amount = parse_user_and_amount(command_text)

    if command_text == 'list' or command_text == 'tally':
        response_msg = get_tally()
    elif lender is None:
        response_msg = "Make sure to include a user who is a member of the team, " \
                       "or use `list` to get the current chip count."
    elif amount is None:
        response_msg = "Make sure to include an amount, or use `list` to get the current chip count."
    elif amount < Decimal(0):
        response_msg = "You can't owe someone negative. Get them to owe you to erase debts."
    elif lender == debtor:
        response_msg = "You can resolve your own debts to yourself. No chips changed!"
    else:
        save_to_db(debtor, lender, amount)
        response_msg = "%s lost %s chips while %s gained %s chips" % (debtor, amount, lender, amount)
        logger.info(response_msg)

    return respond(None, {
        'response_type': 'in_channel',
        'text': response_msg
    })

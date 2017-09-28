import boto3
import time
import os
import re
import logging
from urllib import urlopen, urlencode
import json

table_name = os.environ['TABLE_NAME']  # for example: bookkeepbot_ledger
region_name = os.getenv('REGION_NAME', 'us-east-1')  # for example: ap-northeast-2
slack_token = os.environ['SLACK_WEB_API_TOKEN']

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
dynamo = boto3.client('dynamodb', region_name=region_name)


""" --- Helpers to build responses which match the structure of the necessary dialog actions --- """


def elicit_slot(session_attributes, intent_name, slots, slot_to_elicit, message):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ElicitSlot',
            'intentName': intent_name,
            'slots': slots,
            'slotToElicit': slot_to_elicit,
            'message': message
        }
    }


def delegate(session_attributes, slots):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Delegate',
            'slots': slots
        }
    }


def close(session_attributes, fulfillment_state, message):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Close',
            'fulfillmentState': fulfillment_state,
            'message': message
        }
    }

    return response


""" --- Helper Functions --- """


def get_slack_username(user):
    url = "https://slack.com/api/users.info"
    params = {
        'token': slack_token,
        'user': user,
    }
    params_encoded = urlencode(params)

    resp = urlopen(url, params_encoded)
    return json.load(resp)["user"]["name"]


def isvalid_user(user):
    try:
        get_slack_username(user)
        return True
    except IOError:
        return False
    except KeyError:
        return False


def isvalid_amount(s):
    return re.match(r"(-?)(\$?)(\d\d?(\d+|(,\d\d\d)*)(\.\d+)?|(\.\d+))", s)


def get_amount_in_float(s):
    p_amount = isvalid_amount(s)
    if p_amount:
        logger.debug('FOUNT P_AMOUNT IN GET_AMOUNT_IN_FLOAT')
        return float(p_amount.group(3).replace(',', '').replace('$', ''))
    else:
        logger.debug('ERROR IN GET_AMOUNT_IN_FLOAT')
        return 99.0


def build_validation_result(is_valid, violated_slot, message_content):
    if message_content is None:
        return {
            "isValid": is_valid,
            "violatedSlot": violated_slot,
        }

    return {
        'isValid': is_valid,
        'violatedSlot': violated_slot,
        'message': {'contentType': 'PlainText', 'content': message_content}
    }


def validate_request_debt(lender, amount):
    if lender is not None:
        if not isvalid_user(lender):
            return build_validation_result(False,
                                           'Lender',
                                           '{} is an invalid user. '
                                           'Please enter a user in the Slack team.'.format(lender))

    if amount is not None:
        if not isvalid_amount(amount):
            return build_validation_result(False,
                                           'Amount',
                                           '{} is an invalid amount. '
                                           'Please enter a valid amount of chips.'.format(amount))

    return build_validation_result(True, None, None)


""" --- Helper functions for record_debt --- """


def parse_user_and_amount(debtor, lender, amount):

    user_name = get_slack_username(debtor)
    debtor_escaped = "<@" + debtor + "|" + user_name + ">"

    user_name = get_slack_username(lender)
    lender_escaped = "<@" + lender + "|" + user_name + ">"

    # logger.debug('AMOUNT={}'.format(amount))
    owed_amount = get_amount_in_float(amount)

    return debtor_escaped, lender_escaped, owed_amount


def save_to_db(debtor, lender, amount):  # make sure to use the same keys in DynamoDB
    # subtract amount from debtor
    dynamo.update_item(TableName=table_name,
                       Key={'user': {'S': debtor}},
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


""" --- Helpler functions for get_list --- """


def get_entries():
    res = dynamo.scan(TableName=table_name)

    logger.info(res)

    entry_list = {}
    for item in res['Items']:
        entry_list[item['user']['S']] = item['chips']['N']

    return entry_list


""" --- Functions that control the bot's behavior --- """


def record_debt(intent_request):
    """
    Performs dialog management and fulfillment for recording debt.
    Beyond fulfillment, the implementation of this intent demonstrates the use of the elicitSlot dialog action
    in slot validation and re-prompting.
    """

    debtor = intent_request['userId'].split(":")[2]
    lender = intent_request['currentIntent']['slots']["Lender"]
    if lender and lender[:1] == "@":
        lender = lender[1:]
    amount = intent_request['currentIntent']['slots']["Amount"]
    source = intent_request['invocationSource']

    if source == 'DialogCodeHook':
        # Perform basic validation on the supplied input slots.
        # Use the elicitSlot dialog action to re-prompt for the first violation detected.
        slots = intent_request['currentIntent']['slots']

        validation_result = validate_request_debt(lender, amount)
        if not validation_result['isValid']:
            slots[validation_result['violatedSlot']] = None
            return elicit_slot(intent_request['sessionAttributes'],
                               intent_request['currentIntent']['name'],
                               slots,
                               validation_result['violatedSlot'],
                               validation_result['message'])

        # You can utilize output_session_attributes to add functionality to the bot
        output_session_attributes = intent_request['sessionAttributes'] \
            if intent_request['sessionAttributes'] is not None else {}

        return delegate(output_session_attributes, intent_request['currentIntent']['slots'])

    # Store changes
    debtor_parsed, lender_parsed, amount_parsed = parse_user_and_amount(debtor, lender, amount)
    save_to_db(debtor_parsed, lender_parsed, amount_parsed)

    # Rely on the goodbye message of the bot to define the message to the end user
    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': '{} chips owed to {} has been recorded in my books!'.format(amount, lender_parsed)})


def get_list(intent_request):
    """
    Performs dialog management and fulfillment for recording debt.
    Beyond fulfillment, the implementation of this intent demonstrates the use of the elicitSlot dialog action
    in slot validation and re-prompting.
    """

    ledger = get_entries()

    if ledger:
        response = "This is the current standing:\n"
        response += "```"
        for user, chips in sorted(ledger.items()):
            response += "{:<10}:{:>5}\n".format(user, chips)
        response += "```"
    else:
        response = "There are no unpaid debts in this group! :smile:"

    # Rely on the goodbye message of the bot to define the message to the end user
    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': '{}'.format(response)})


""" --- Intents --- """


def dispatch(intent_request):
    """
    Called when the user specifies an intent for this bot.
    """

    logger.debug('INTENT_REQUEST={}'.format(intent_request))

    intent_name = intent_request['currentIntent']['name']

    # Dispatch to bot's intent handlers
    if intent_name == 'record_debt':
        return record_debt(intent_request)
    if intent_name == 'get_list':
        return get_list(intent_request)

    raise Exception('Intent with name ' + intent_name + ' not supported')


""" --- Main handler --- """


def lambda_handler(event, context):
    """
    Route the incoming request based on intent.
    The JSON body of the request is provided in the event slot.
    """
    # By default, treat the user request as coming from the Asia/Seoul time zone.
    os.environ['TZ'] = 'Asia/Seoul'
    time.tzset()
    logger.debug('event.bot.name={}'.format(event['bot']['name']))

    return dispatch(event)

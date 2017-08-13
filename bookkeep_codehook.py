"""
An implementation of the Lex Code Hook Interface based on AWS sample bot which manages orders for flowers.
"""
import boto3
import time
import os
import logging
from urllib import urlopen, urlencode
import json

table_name = os.environ['TABLE_NAME']  # for example: bookkeepbot_ledger
region_name = os.getenv('REGION_NAME', 'ap-northeast-2')  # for example: ap-northeast-2
slack_token = os.environ['SLACK_WEB_API_TOKEN']

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
dynamo = boto3.client('dynamodb', region_name=region_name)


""" --- Helpers to build responses which match the structure of the necessary dialog actions --- """


def get_slots(intent_request):
    return intent_request['currentIntent']['slots']


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


def delegate(session_attributes, slots):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Delegate',
            'slots': slots
        }
    }


""" --- Helper Functions --- """


def isvalid_user(user):
    url = "https://slack.com/api/users.info"
    params = {
        'token': slack_token,
        'user': user,
    }
    params_encoded = urlencode(params)

    try:
        resp = urlopen(url, params_encoded)
        json.load(resp)["user"]["name"]
        return True
    except IOError:
        return False
    except KeyError:
        return False


def isvalid_float(s):
    return s.replace('.', '', 1).isdigit()


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
        if not isvalid_float(amount):
            return build_validation_result(False,
                                           'Amount',
                                           '{} is an invalid amount. '
                                           'Please enter a valid amount of chips.'.format(amount))

    return build_validation_result(True, None, None)


""" --- Helper functions for record_debt --- """


def parse_user_and_amount(debtor, lender, amount):

    url = "https://slack.com/api/users.info"
    params = {
        'token': slack_token,
        'user': lender,
    }
    params_encoded = urlencode(params)

    resp = urlopen(url, params_encoded)
    user_name = json.load(resp)["user"]["name"]
    lender_escaped = "<@" + lender + "|" + user_name + ">"

    params = {
        'token': slack_token,
        'user': debtor,
    }
    params_encoded = urlencode(params)

    resp = urlopen(url, params_encoded)
    user_name = json.load(resp)["user"]["name"]
    debtor_escaped = "<@" + debtor + "|" + user_name + ">"

    owed_amount = float(amount)

    return debtor_escaped, lender_escaped, owed_amount


def save_to_db(user, owed_user, owed_amount):  # make sure to use the same keys in DynamoDB
    # subtract owed_amount from user
    dynamo.update_item(TableName=table_name,
        Key={'user_id':{'S':user}},
        AttributeUpdates= {
            'chips':{
                'Action': 'ADD',
                'Value': {'N': str(-owed_amount)}
            }
        }
    )

    # add owed_amount to owed_user
    dynamo.update_item(TableName=table_name,
        Key={'user_id': {'S':owed_user}},
        AttributeUpdates= {
            'chips':{
                'Action': 'ADD',
                'Value': {'N': str(owed_amount)}
            }
        }
    )


""" --- Functions that control the bot's behavior --- """


def record_debt(intent_request):
    """
    Performs dialog management and fulfillment for ordering flowers.
    Beyond fulfillment, the implementation of this intent demonstrates the use of the elicitSlot dialog action
    in slot validation and re-prompting.
    """

    debtor_raw = intent_request['userId']
    debtor = debtor_raw.split(":")[2]
    lender = get_slots(intent_request)["Lender"]
    amount = get_slots(intent_request)["Amount"]
    source = intent_request['invocationSource']

    if source == 'DialogCodeHook':
        # Perform basic validation on the supplied input slots.
        # Use the elicitSlot dialog action to re-prompt for the first violation detected.
        slots = get_slots(intent_request)

        validation_result = validate_request_debt(lender, amount)
        if not validation_result['isValid']:
            slots[validation_result['violatedSlot']] = None
            return elicit_slot(intent_request['sessionAttributes'],
                               intent_request['currentIntent']['name'],
                               slots,
                               validation_result['violatedSlot'],
                               validation_result['message'])

        # TODO: Utilize output_session_attributes
        output_session_attributes = intent_request['sessionAttributes'] if intent_request['sessionAttributes'] is not None else {}

        return delegate(output_session_attributes, get_slots(intent_request))

    # Store changes, and rely on the goodbye message of the bot to define the message to the end user. (Lex goodbye message is not displayed)
    user, owed_user, owed_amount = parse_user_and_amount(debtor, lender, amount)
    save_to_db(user, owed_user, owed_amount)

    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': 'Okay, I have successfully recorded {} chips owed to {} in my books'.format(amount, lender)})


""" --- Intents --- """


def dispatch(intent_request):
    """
    Called when the user specifies an intent for this bot.
    """

    logger.debug('dispatch userId={}, intentName={}'.format(intent_request['userId'], intent_request['currentIntent']['name']))

    intent_name = intent_request['currentIntent']['name']

    # Dispatch to your bot's intent handlers
    if intent_name == 'record_debt':
        return record_debt(intent_request)

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

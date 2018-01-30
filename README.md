# BookkeepBot
Bookkeep Bot is a Slack bot that handles bookkeeping for users within a Slack team.

It has two modules:
- The [slash command](https://github.com/mjkim610/bookkeepbot/blob/master/bookkeepbot_slashcommand_lambda.py) uses Slack's slash command API and can be accessed by typing `/bookkeepbot`.
- The [chatbot](https://github.com/mjkim610/bookkeepbot/blob/master/bookkeepbot_lex_codehook.py) is a bot user inside the Slack team. It uses AWS Lex, which means it is typo-tolerant.

## Demo
![BookkeepBot Demo](/resources/demo.gif)

## Architecture
![BookkeepBot Architecture](/resources/architecture.png)

## Acknowledgement
- Slash command tutorial: https://www.thorntech.com/2017/03/serverless-slack-chatbot/
- AWS documentation and sample code: https://docs.aws.amazon.com/lex/latest/dg/what-is.html

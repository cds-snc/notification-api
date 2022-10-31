// used to check the email inbox
const imaps = require('imap-simple')
// used to parse emails from the inbox
const simpleParser = require('mailparser').simpleParser

const emailAccount = async () => {

    const emailConfig = {
        imap: {
            user: 'alexcampbell1861@gmail.com',
            password: 'atvk ybkc lleh yzcd',//'a5RPvvaGEEKd46KvjA',
            host: 'imap.gmail.com',
            port: 993,
            tls: true,
            authTimeout: 10000,
        },
    }

    const userEmail = {
        /**
         * Utility method for getting the last email
         * for the Ethereal email account
         */
        async deleteAllEmails() {
            console.log('purging the inbox')
            console.log(emailConfig)

            try {
                const connection = await imaps.connect(emailConfig)

                // grab up to 50 emails from the inbox
                await connection.openBox('INBOX')
                const searchCriteria = ['1:50']
                const fetchOptions = {
                    bodies: [''],
                }
                const messages = await connection.search(searchCriteria, fetchOptions)

                if (!messages.length) {
                    console.log('cannot find any emails')
                    // and close the connection to avoid it hanging
                    connection.end()
                    return null
                } else {
                    console.log('there are %d messages', messages.length)
                    // delete all messages
                    const uidsToDelete = messages
                        .filter(message => {
                            return message.parts
                        })
                        .map(message => message.attributes.uid);

                    console.log('del', uidsToDelete);
                    if (uidsToDelete.length > 0) {
                        await connection.deleteMessage(uidsToDelete);
                    }
                    // and close the connection to avoid it hanging
                    connection.end()

                    // and returns the main fields
                    return {
                        subject: mail.subject,
                        text: mail.text,
                        html: mail.html,
                    }
                }
            } catch (e) {
                // and close the connection to avoid it hanging
                // connection.end()
                console.error(e)
                return null
            }
        },
        /**
         * Utility method for getting the last email
         * for the Ethereal email account 
         */
        async getLastEmail() {
            // makes debugging very simple
            console.log('getting the last email')
            console.log(emailConfig)

            try {
                const connection = await imaps.connect(emailConfig)

                // grab up to 50 emails from the inbox
                await connection.openBox('INBOX')
                const searchCriteria = ['1:50', 'UNDELETED']
                const fetchOptions = {
                    bodies: [''],
                }
                const messages = await connection.search(searchCriteria, fetchOptions)
                // and close the connection to avoid it hanging
                connection.end()

                if (!messages.length) {
                    console.log('cannot find any emails')
                    return null
                } else {
                    console.log('there are %d messages', messages.length)
                    // grab the last email
                    const mail = await simpleParser(
                        messages[messages.length - 1].parts[0].body,
                    )
                    console.log(mail.subject)
                    console.log(mail.text)


                    // and returns the main fields
                    return {
                        subject: mail.subject,
                        text: mail.text,
                        html: mail.html,
                    }
                }
            } catch (e) {
                // and close the connection to avoid it hanging
                // connection.end()

                console.error(e)
                return null
            }
        },
    }

    return userEmail
}

module.exports = emailAccount

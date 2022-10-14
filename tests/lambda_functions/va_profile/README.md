# Unit Testing VA Profile Integration

Integration with VA Profile utilizes several forms of authentication.  When VA Profile makes a POST request to the endpoint for updating the opt-in/out local cache, that request should contain an "Authorization" header with a value in the "Bearer" format.  This is a [JSON Web Token](https://en.wikipedia.org/wiki/JSON_Web_Token), and it should be asymmetrically signed with VA Profile's private key.  The lambda code authenticates VA Profile by verifying this signature, which requires a public key.  To unit test this functionality, this directory contains *cert.pem* and *key.pem*.  The password associated with the latter is "test".

You can generate .pem files as described [here](https://stackoverflow.com/questions/47401714/generate-a-public-private-key-pair-in-pem-format#47447242).

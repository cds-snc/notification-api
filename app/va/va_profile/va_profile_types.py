from typing import TypedDict, List


class Country(TypedDict):
    countryName: str
    countryCodeFIPS: str
    countryCodeISO2: str
    countryCodeISO3: str


class State(TypedDict):
    stateName: str
    stateCode: str


class County(TypedDict):
    countyName: str
    countyCode: str


class Address(TypedDict):
    createDate: str
    updateDate: str
    txAuditId: str
    sourceSystem: str
    sourceDate: str
    originatingSourceSystem: str
    sourceSystemUser: str
    effectiveStartDate: str
    vaProfileId: int
    addressId: int
    addressType: str
    addressPOU: str
    addressLine1: str
    cityName: str
    state: State
    zipCode5: str
    zipCode4: str
    county: County
    country: Country
    latitude: str
    longitude: str
    geocodePrecision: str
    geocodeDate: str


class Telephone(TypedDict):
    createDate: str
    updateDate: str
    txAuditId: str
    sourceSystem: str
    sourceDate: str
    originatingSourceSystem: str
    sourceSystemUser: str
    effectiveStartDate: str
    vaProfileId: int
    telephoneId: int
    internationalIndicator: bool
    phoneType: str
    countryCode: str
    areaCode: str
    phoneNumber: str


class Email(TypedDict):
    createDate: str
    updateDate: str
    txAuditId: str
    sourceSystem: str
    sourceDate: str
    originatingSourceSystem: str
    sourceSystemUser: str
    effectiveStartDate: str
    vaProfileId: int
    emailId: int
    emailAddressText: str


class ContactInformation(TypedDict):
    createDate: str
    updateDate: str
    txAuditId: str
    sourceSystem: str
    sourceDate: str
    sourceSystemUser: str
    vaProfileId: int
    addresses: List[Address]
    telephones: List[Telephone]
    emails: List[Email]


class CommunicationPermissions(TypedDict):
    createDate: str
    updateDate: str
    txAuditId: str
    sourceSystem: str
    sourceDate: str
    communicationPermissionID: int
    vaProfileId: int
    communicationChannelId: int
    communicationItemId: int
    communicationChannelName: str
    communicationItemCommonName: str
    allowed: bool
    confirmationDate: List[str]


class Profile(TypedDict):
    contactInformation: ContactInformation
    communicationPermissions: List[CommunicationPermissions]

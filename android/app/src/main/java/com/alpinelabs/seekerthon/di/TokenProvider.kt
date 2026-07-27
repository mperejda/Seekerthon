package com.alpinelabs.seekerthon.di

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class TokenProvider @Inject constructor(
    private val dataStore: DataStore<Preferences>,
) {
    companion object {
        private val TOKEN_KEY = stringPreferencesKey("jwt_token")
        private val TERMS_VERSION_KEY = stringPreferencesKey("terms_version")
        private const val CURRENT_TERMS_VERSION = "2026-07-26"
    }

    fun getToken(): String? = runBlocking {
        dataStore.data.first()[TOKEN_KEY]
    }

    suspend fun saveToken(token: String) {
        dataStore.edit { it[TOKEN_KEY] = token }
    }

    suspend fun clearToken() {
        dataStore.edit { it.remove(TOKEN_KEY) }
    }

    fun hasAcceptedCurrentTerms(): Boolean = runBlocking {
        dataStore.data.first()[TERMS_VERSION_KEY] == CURRENT_TERMS_VERSION
    }

    suspend fun acceptCurrentTerms() {
        dataStore.edit { it[TERMS_VERSION_KEY] = CURRENT_TERMS_VERSION }
    }
}

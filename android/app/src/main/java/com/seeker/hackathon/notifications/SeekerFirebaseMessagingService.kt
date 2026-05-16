package com.seeker.hackathon.notifications

import android.app.PendingIntent
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.seeker.hackathon.MainActivity
import com.seeker.hackathon.R
import com.seeker.hackathon.SeekerApp.Companion.NOTIFICATION_CHANNEL_ID
import com.seeker.hackathon.data.remote.DeviceTokenDto
import com.seeker.hackathon.data.remote.SeekerApi
import com.seeker.hackathon.di.TokenProvider
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class SeekerFirebaseMessagingService : FirebaseMessagingService() {

    @Inject lateinit var api: SeekerApi
    @Inject lateinit var tokenProvider: TokenProvider

    override fun onNewToken(token: String) {
        val jwt = tokenProvider.getToken() ?: return
        CoroutineScope(Dispatchers.IO).launch {
            runCatching { api.registerDeviceToken(DeviceTokenDto(token)) }
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val title = message.notification?.title ?: message.data["title"] ?: return
        val body = message.notification?.body ?: message.data["body"] ?: return
        showNotification(title, body)
    }

    private fun showNotification(title: String, body: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent, PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(this)
            .notify(System.currentTimeMillis().toInt(), notification)
    }
}

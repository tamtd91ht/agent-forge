package com.example.search;

import io.vertx.core.AbstractVerticle;
import io.vertx.core.Promise;
import io.vertx.ext.web.Router;

public class SearchVerticle extends AbstractVerticle {
    @Override
    public void start(Promise<Void> startPromise) {
        Router router = Router.router(vertx);
        router.get("/search").handler(ctx -> ctx.response().end("[]"));
        vertx.createHttpServer().requestHandler(router).listen(8080)
            .onSuccess(s -> startPromise.complete())
            .onFailure(startPromise::fail);
    }
}

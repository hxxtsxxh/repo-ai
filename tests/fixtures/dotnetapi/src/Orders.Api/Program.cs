var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/orders/{id}", (int id) => OrderService.Find(id));
app.Run();
